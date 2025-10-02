from typing import Iterable, List, Optional

from django.contrib.auth.models import AbstractUser

from baserow.contrib.automation.models import AutomationWorkflow
from baserow.contrib.automation.nodes.exceptions import (
    AutomationNodeBeforeInvalid,
    AutomationNodeNotMovable,
    AutomationTriggerModificationDisallowed,
)
from baserow.contrib.automation.nodes.handler import AutomationNodeHandler
from baserow.contrib.automation.nodes.models import AutomationActionNode, AutomationNode
from baserow.contrib.automation.nodes.node_types import AutomationNodeType
from baserow.contrib.automation.nodes.operations import (
    CreateAutomationNodeOperationType,
    DeleteAutomationNodeOperationType,
    DuplicateAutomationNodeOperationType,
    ListAutomationNodeOperationType,
    OrderAutomationNodeOperationType,
    ReadAutomationNodeOperationType,
    UpdateAutomationNodeOperationType,
)
from baserow.contrib.automation.nodes.registries import (
    ReplaceAutomationNodeTrashOperationType,
    automation_node_type_registry,
)
from baserow.contrib.automation.nodes.signals import (
    automation_node_created,
    automation_node_deleted,
    automation_node_replaced,
    automation_node_updated,
    automation_nodes_reordered,
    automation_nodes_updated,
)
from baserow.contrib.automation.nodes.types import (
    AutomationNodeDuplication,
    AutomationNodeMove,
    NextAutomationNodeValues,
    ReplacedAutomationNode,
    UpdatedAutomationNode,
)
from baserow.core.handler import CoreHandler
from baserow.core.trash.handler import TrashHandler


class AutomationNodeService:
    def __init__(self):
        self.handler = AutomationNodeHandler()

    def get_node(self, user: AbstractUser, node_id: int) -> AutomationNode:
        """
        Returns an AutomationNode instance by its ID.

        :param user: The user trying to get the workflow_actions.
        :param node_id: The ID of the node.
        :return: The node instance.
        """

        node = self.handler.get_node(node_id)

        CoreHandler().check_permissions(
            user,
            ReadAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node,
        )

        return node

    def get_nodes(
        self,
        user: AbstractUser,
        workflow: AutomationWorkflow,
        specific: Optional[bool] = True,
    ) -> Iterable[AutomationNode]:
        """
        Returns all the automation nodes for a specific workflow that can be
        accessed by the user.

        :param user: The user trying to get the workflow_actions.
        :param workflow: The workflow the automation node is associated with.
        :param specific: If True, returns the specific node type.
        :return: The automation nodes of the workflow.
        """

        CoreHandler().check_permissions(
            user,
            ListAutomationNodeOperationType.type,
            workspace=workflow.automation.workspace,
            context=workflow,
        )

        user_nodes = CoreHandler().filter_queryset(
            user,
            ListAutomationNodeOperationType.type,
            AutomationNode.objects.all(),
            workspace=workflow.automation.workspace,
        )

        return self.handler.get_nodes(
            workflow, specific=specific, base_queryset=user_nodes
        )

    def create_node(
        self,
        user: AbstractUser,
        node_type: AutomationNodeType,
        workflow: AutomationWorkflow,
        before: Optional[AutomationNode] = None,
        order: Optional[str] = None,
        **kwargs,
    ) -> AutomationNode:
        """
        Creates a new automation node for a workflow given the user permissions.

        :param user: The user trying to create the automation node.
        :param node_type: The type of the automation node.
        :param workflow: The workflow the automation node is associated with.
        :param before: If set, the new node is inserted before this node.
        :param order: The order of the new node. If not set, it will be determined
            automatically based on the existing nodes in the workflow.
        :param kwargs: Additional attributes of the automation node.
        :raises AutomationTriggerModificationDisallowed: If the node_type is a trigger.
        :return: The created automation node.
        """

        # Triggers are not directly created by users. When a workflow is created,
        # the trigger node is created automatically, so users are only able to change
        # the trigger node type, not create a new one.
        if node_type.is_workflow_trigger:
            raise AutomationTriggerModificationDisallowed()

        CoreHandler().check_permissions(
            user,
            CreateAutomationNodeOperationType.type,
            workspace=workflow.automation.workspace,
            context=workflow,
        )

        # If we've been given a `before` node, validate it.
        if before:
            if workflow.id != before.workflow_id:
                raise AutomationNodeBeforeInvalid(
                    "The `before` node must belong to the same workflow "
                    "as the one supplied."
                )
            if not before.previous_node_id:
                # You can't create a node before a trigger node. Even if `node_type` is
                # a trigger, API consumers must delete `before` and then try again.
                raise AutomationNodeBeforeInvalid(
                    "You cannot create an automation node before a trigger."
                )

        prepared_values = node_type.prepare_values(kwargs, user)

        new_node = self.handler.create_node(
            node_type, order=order, workflow=workflow, before=before, **prepared_values
        )
        node_type.after_create(new_node)

        automation_node_created.send(
            self,
            node=new_node,
            user=user,
        )

        return new_node

    def update_node(
        self, user: AbstractUser, node_id: int, **kwargs
    ) -> UpdatedAutomationNode:
        """
        Updates fields of a node.

        :param user: The user trying to update the node.
        :param node_id: The node that should be updated.
        :param kwargs: The fields that should be updated with their corresponding value
        :return: UpdatedAutomationNode.
        """

        node = self.handler.get_node(node_id)
        node_type = node.get_type()

        CoreHandler().check_permissions(
            user,
            UpdateAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node,
        )

        # Export the 'original' node values now, as `prepare_values`
        # will be changing the service first, and then `update_node`
        # will be change the node itself.
        original_node_values = node_type.export_prepared_values(node)

        # Prepare the node's values, which handles service updates too.
        prepared_values = node_type.prepare_values(kwargs, user, node)

        # Update the node itself.
        updated_node = self.handler.update_node(node, **prepared_values)

        # Now export the 'new' node values, since everything has been updated.
        new_node_values = node_type.export_prepared_values(node)

        automation_node_updated.send(self, user=user, node=updated_node)

        return UpdatedAutomationNode(
            node=updated_node,
            original_values=original_node_values,
            new_values=new_node_values,
        )

    def update_next_nodes_values(
        self,
        user: AbstractUser,
        next_node_values: List[NextAutomationNodeValues],
        workflow: AutomationWorkflow,
    ) -> List[AutomationActionNode]:
        """
        Update the next nodes values for a list of nodes.

        :param user: The user trying to update the next node values.
        :param next_node_values: The new next node values.
        :param workflow: The workflow the nodes belong to.
        :return: The updated nodes.
        """

        updated_next_nodes = self.handler.update_next_nodes_values(next_node_values)
        if updated_next_nodes:
            automation_nodes_updated.send(
                self, user=user, nodes=updated_next_nodes, workflow=workflow
            )

        return updated_next_nodes

    def delete_node(
        self,
        user: AbstractUser,
        node_id: int,
        trash_operation_type: Optional[str] = None,
    ) -> AutomationNode:
        """
        Deletes the specified automation node.

        :param user: The user trying to delete the node.
        :param node_id: The ID of the node to delete.
        :param trash_operation_type: The trash operation type to use when trashing
            the node.
        :return: The deleted node.
        :raises AutomationTriggerModificationDisallowed: If the node is a trigger.
        """

        node = self.handler.get_node(node_id)

        CoreHandler().check_permissions(
            user,
            DeleteAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node,
        )

        automation = node.workflow.automation
        trash_entry = TrashHandler.trash(
            user,
            automation.workspace,
            automation,
            node,
            trash_operation_type=trash_operation_type,
        )

        if trash_entry.get_operation_type().send_post_trash_deleted_signal:
            automation_node_deleted.send(
                self,
                workflow=node.workflow,
                node_id=node.id,
                user=user,
            )

        return node

    def order_nodes(
        self, user: AbstractUser, workflow: AutomationWorkflow, order: List[int]
    ) -> List[int]:
        """
        Assigns a new order to the nodes in a workflow.

        :param user: The user trying to order the workflows.
        :param workflow The workflow that the nodes belong to.
        :param order: The new order of the nodes.
        :return: The new order of the nodes.
        """

        automation = workflow.automation
        CoreHandler().check_permissions(
            user,
            OrderAutomationNodeOperationType.type,
            workspace=automation.workspace,
            context=workflow,
        )

        all_nodes = self.handler.get_nodes(
            workflow, specific=False, base_queryset=AutomationNode.objects
        )

        user_nodes = CoreHandler().filter_queryset(
            user,
            OrderAutomationNodeOperationType.type,
            all_nodes,
            workspace=automation.workspace,
        )

        new_order = self.handler.order_nodes(workflow, order, user_nodes)

        automation_nodes_reordered.send(
            self, workflow=workflow, order=new_order, user=user
        )

        return new_order

    def duplicate_node(
        self,
        user: AbstractUser,
        node: AutomationNode,
    ) -> AutomationNodeDuplication:
        """
        Duplicates an existing AutomationNode instance.

        :param user: The user initiating the duplication.
        :param node: The node that is being duplicated.
        :raises ValueError: When the provided node is not an instance of
            AutomationNode.
        :raises AutomationTriggerModificationDisallowed: If the node is a trigger.
        :return: The `AutomationNodeDuplication` dataclass containing the source
            node, its next nodes values and the duplicated node.
        """

        CoreHandler().check_permissions(
            user,
            DuplicateAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node,
        )

        # If we received a trigger node, we cannot duplicate it.
        if node.get_type().is_workflow_trigger:
            raise AutomationTriggerModificationDisallowed()

        duplication = self.handler.duplicate_node(node)

        automation_node_created.send(
            self,
            node=duplication.duplicated_node,
            user=user,
        )

        return duplication

    def replace_node(
        self,
        user: AbstractUser,
        node_id: int,
        new_node_type_str: str,
    ) -> ReplacedAutomationNode:
        """
        Replaces an existing automation node with a new one of a different type.

        :param user: The user trying to replace the node.
        :param node_id: The ID of the node to replace.
        :param new_node_type_str: The type of the new node to replace with.
        :return: The replaced automation node.
        """

        node = self.get_node(user, node_id)
        node_type: AutomationNodeType = node.get_type()

        CoreHandler().check_permissions(
            user,
            CreateAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node.workflow,
        )

        new_node_type = automation_node_type_registry.get(new_node_type_str)
        node_type.before_replace(node, new_node_type)

        prepared_values = new_node_type.prepare_values(
            {},
            user,
        )

        new_node = self.handler.create_node(
            new_node_type,
            workflow=node.workflow,
            before=node,
            order=node.order,
            **prepared_values,
        )

        new_node_type.after_create(new_node)

        # After the node creation, the replaced node has changed
        node.refresh_from_db()

        # Trash the old node, assigning it a specific trash operation
        # type so that we know it was replaced when restoring it.
        automation = node.workflow.automation
        TrashHandler.trash(
            user,
            automation.workspace,
            automation,
            node,
            trash_operation_type=ReplaceAutomationNodeTrashOperationType.type,
        )

        automation_node_replaced.send(
            self,
            workflow=new_node.workflow,
            restored_node=new_node,
            deleted_node=node,
            user=user,
        )

        return ReplacedAutomationNode(
            node=new_node,
            original_node_id=node.id,
            original_node_type=node_type.type,
        )

    def simulate_dispatch_node(
        self, user: AbstractUser, node_id: int
    ) -> AutomationNode:
        """
        Simulates the dispatch of an automation node.

        :param user: The user trying to simulate the node dispatch.
        :param node_id: The ID of the node to dispatch.
        :return: The updated node.
        """

        node = self.get_node(user, node_id)

        CoreHandler().check_permissions(
            user,
            UpdateAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node,
        )

        return self.handler.simulate_dispatch_node(node)

    def move_node(
        self,
        user: AbstractUser,
        node_id: int,
        new_previous_node_id: int,
        new_previous_output: Optional[str] = None,
        new_order: Optional[float] = None,
    ) -> AutomationNodeMove:
        """
        Moves an existing automation node to a new position in the workflow.

        :param user: The user trying to move the node.
        :param node_id: The ID of the node to move.
        :param new_previous_node_id: The ID of the node that
            will be the new previous node.
        :param new_previous_output: If the destination is an output, the output uid.
        :param new_order: The new order of the node. If not provided, it will
            be calculated to be last of `new_previous_node_id`.
        :raises AutomationNodeNotMovable: If the node cannot be moved.
        :return: The move operation details.
        """

        node = self.get_node(user, node_id)
        node_type: AutomationNodeType = node.get_type()

        CoreHandler().check_permissions(
            user,
            UpdateAutomationNodeOperationType.type,
            workspace=node.workflow.automation.workspace,
            context=node,
        )

        # If a node type cannot move, raise an exception.
        if node_type.is_fixed:
            raise AutomationNodeNotMovable("This automation node cannot be moved.")

        after_node = self.get_node(user, new_previous_node_id)
        move = self.handler.move_node(node, after_node, new_previous_output, new_order)

        updated_nodes = [move.node] + move.next_node_updates
        automation_nodes_updated.send(
            self,
            user=user,
            nodes=updated_nodes,
            workflow=node.workflow,
        )

        return move
