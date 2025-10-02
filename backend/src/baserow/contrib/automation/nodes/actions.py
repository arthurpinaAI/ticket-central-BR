from dataclasses import dataclass
from typing import Any, List

from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

from baserow.contrib.automation.action_scopes import (
    NODE_ACTION_CONTEXT,
    WorkflowActionScopeType,
)
from baserow.contrib.automation.actions import AUTOMATION_WORKFLOW_CONTEXT
from baserow.contrib.automation.nodes.handler import AutomationNodeHandler
from baserow.contrib.automation.nodes.models import AutomationNode
from baserow.contrib.automation.nodes.node_types import AutomationNodeType
from baserow.contrib.automation.nodes.registries import (
    ReplaceAutomationNodeTrashOperationType,
)
from baserow.contrib.automation.nodes.service import AutomationNodeService
from baserow.contrib.automation.nodes.signals import automation_node_replaced
from baserow.contrib.automation.nodes.trash_types import AutomationNodeTrashableItemType
from baserow.contrib.automation.nodes.types import NextAutomationNodeValues
from baserow.contrib.automation.workflows.models import AutomationWorkflow
from baserow.contrib.automation.workflows.service import AutomationWorkflowService
from baserow.core.action.models import Action
from baserow.core.action.registries import ActionTypeDescription, UndoableActionType
from baserow.core.trash.handler import TrashHandler


class CreateAutomationNodeActionType(UndoableActionType):
    type = "create_automation_node"
    description = ActionTypeDescription(
        _("Create automation node"),
        _("Node (%(node_id)s) created"),
        NODE_ACTION_CONTEXT,
    )

    @dataclass
    class Params:
        automation_id: int
        automation_name: str
        node_id: int
        node_type: str

    @classmethod
    def do(
        cls,
        user: AbstractUser,
        node_type: AutomationNodeType,
        workflow: AutomationWorkflow,
        data: dict,
    ) -> AutomationNode:
        before_id = data.pop("before_id", None)
        before = (
            AutomationNodeService().get_node(user, before_id) if before_id else None
        )

        node = AutomationNodeService().create_node(
            user, node_type, workflow, before, **data
        )

        cls.register_action(
            user=user,
            params=cls.Params(
                node.workflow.automation.id,
                node.workflow.automation.name,
                node.id,
                node.get_type().type,
            ),
            scope=cls.scope(node.workflow.id),
            workspace=node.workflow.automation.workspace,
        )
        return node

    @classmethod
    def scope(cls, workflow_id):
        return WorkflowActionScopeType.value(workflow_id)

    @classmethod
    def undo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_undo: Action,
    ):
        AutomationNodeService().delete_node(user, params.node_id)

    @classmethod
    def redo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_redo: Action,
    ):
        TrashHandler.restore_item(
            user,
            AutomationNodeTrashableItemType.type,
            params.node_id,
        )


class UpdateAutomationNodeActionType(UndoableActionType):
    type = "update_automation_node"
    description = ActionTypeDescription(
        _("Update automation node"),
        _("Node (%(node_id)s) updated"),
        NODE_ACTION_CONTEXT,
    )

    @dataclass
    class Params:
        automation_id: int
        automation_name: str
        node_id: int
        node_type: str
        node_original_params: dict[str, Any]
        node_new_params: dict[str, Any]

    @classmethod
    def do(
        cls,
        user: AbstractUser,
        node_id: int,
        new_data: dict,
    ) -> AutomationNode:
        updated_node = AutomationNodeService().update_node(user, node_id, **new_data)

        cls.register_action(
            user=user,
            params=cls.Params(
                updated_node.node.workflow.automation.id,
                updated_node.node.workflow.automation.name,
                updated_node.node.id,
                updated_node.node.get_type().type,
                updated_node.original_values,
                updated_node.new_values,
            ),
            scope=cls.scope(updated_node.node.workflow.id),
            workspace=updated_node.node.workflow.automation.workspace,
        )

        return updated_node.node

    @classmethod
    def scope(cls, workflow_id):
        return WorkflowActionScopeType.value(workflow_id)

    @classmethod
    def undo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_undo: Action,
    ):
        AutomationNodeService().update_node(
            user, params.node_id, **params.node_original_params
        )

    @classmethod
    def redo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_redo: Action,
    ):
        AutomationNodeService().update_node(
            user, params.node_id, **params.node_new_params
        )


class DeleteAutomationNodeActionType(UndoableActionType):
    type = "delete_automation_node"
    description = ActionTypeDescription(
        _("Delete automation node"),
        _("Node (%(node_id)s) deleted"),
        NODE_ACTION_CONTEXT,
    )

    @dataclass
    class Params:
        automation_id: int
        automation_name: str
        node_id: int
        node_type: str

    @classmethod
    def do(cls, user: AbstractUser, node_id: int) -> None:
        node = AutomationNodeService().delete_node(user, node_id)
        automation = node.workflow.automation
        cls.register_action(
            user=user,
            params=cls.Params(
                automation.id,
                automation.name,
                node_id,
                node.get_type().type,
            ),
            scope=cls.scope(node.workflow.id),
            workspace=automation.workspace,
        )

    @classmethod
    def scope(cls, workflow_id):
        return WorkflowActionScopeType.value(workflow_id)

    @classmethod
    def undo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_undo: Action,
    ):
        TrashHandler.restore_item(
            user,
            AutomationNodeTrashableItemType.type,
            params.node_id,
        )

    @classmethod
    def redo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_redo: Action,
    ):
        AutomationNodeService().delete_node(user, params.node_id)


class OrderAutomationNodesActionType(UndoableActionType):
    type = "order_automation_nodes"
    description = ActionTypeDescription(
        _("Order nodes"),
        _("Node order changed"),
        AUTOMATION_WORKFLOW_CONTEXT,
    )

    @dataclass
    class Params:
        workflow_id: int
        nodes_order: List[int]
        original_nodes_order: List[int]
        automation_name: str
        automation_id: int

    @classmethod
    def do(cls, user: AbstractUser, workflow_id: int, order: List[int]) -> None:
        workflow = AutomationWorkflowService().get_workflow(user, workflow_id)

        original_nodes_order = AutomationNodeHandler().get_nodes_order(workflow)
        params = cls.Params(
            workflow_id,
            order,
            original_nodes_order,
            workflow.automation.name,
            workflow.automation.id,
        )

        AutomationNodeService().order_nodes(user, workflow, order=order)

        cls.register_action(
            user=user,
            params=params,
            scope=cls.scope(workflow_id),
            workspace=workflow.automation.workspace,
        )

    @classmethod
    def scope(cls, workflow_id):
        return WorkflowActionScopeType.value(workflow_id)

    @classmethod
    def undo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_undo: Action,
    ):
        AutomationNodeService().order_nodes(
            user,
            AutomationWorkflowService().get_workflow(user, params.workflow_id),
            order=params.original_nodes_order,
        )

    @classmethod
    def redo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_redo: Action,
    ):
        AutomationNodeService().order_nodes(
            user,
            AutomationWorkflowService().get_workflow(user, params.workflow_id),
            order=params.nodes_order,
        )


class DuplicateAutomationNodeActionType(UndoableActionType):
    type = "duplicate_automation_node"
    description = ActionTypeDescription(
        _("Duplicate automation node"),
        _("Node (%(node_id)s) duplicated"),
        NODE_ACTION_CONTEXT,
    )

    @dataclass
    class Params:
        automation_id: int
        automation_name: str
        workflow_id: int
        node_id: int  # The source node id
        node_type: str  # The source node type
        source_node_next_nodes_values: List[NextAutomationNodeValues]
        duplicated_node_id: int
        duplicated_node_next_nodes_values: List[NextAutomationNodeValues]

    @classmethod
    def do(
        cls,
        user: AbstractUser,
        source_node_id: int,
    ) -> AutomationNode:
        source_node = AutomationNodeService().get_node(user, source_node_id)
        duplication = AutomationNodeService().duplicate_node(user, source_node)
        workflow = source_node.workflow
        cls.register_action(
            user=user,
            params=cls.Params(
                workflow.automation_id,
                workflow.automation.name,
                workflow.id,
                source_node_id,
                source_node.get_type().type,
                duplication.source_node_next_nodes_values,
                duplication.duplicated_node.id,
                duplication.duplicated_node_next_nodes_values,
            ),
            scope=cls.scope(workflow.id),
            workspace=workflow.automation.workspace,
        )
        return duplication.duplicated_node

    @classmethod
    def scope(cls, workflow_id):
        return WorkflowActionScopeType.value(workflow_id)

    @classmethod
    def undo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_undo: Action,
    ):
        # Trash the duplicated node.
        AutomationNodeService().delete_node(user, params.duplicated_node_id)

        # Revert any next nodes to point back to the source node.
        AutomationNodeHandler().update_next_nodes_values(
            params.source_node_next_nodes_values
        )

    @classmethod
    def redo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_redo: Action,
    ):
        # Restore the duplicated node again.
        TrashHandler.restore_item(
            user,
            AutomationNodeTrashableItemType.type,
            params.duplicated_node_id,
        )

        # Revert any next nodes to point back to the duplicated node.
        AutomationNodeHandler().update_next_nodes_values(
            params.duplicated_node_next_nodes_values
        )


class ReplaceAutomationNodeActionType(UndoableActionType):
    type = "replace_automation_node"
    description = ActionTypeDescription(
        _("Replace automation node"),
        _(
            "Node (%(node_id)s) changed from a type "
            "of %(original_node_type)s to %(node_type)s"
        ),
        NODE_ACTION_CONTEXT,
    )

    @dataclass
    class Params:
        automation_id: int
        automation_name: str
        workflow_id: int
        node_id: int
        node_type: str
        original_node_id: int
        original_node_type: str

    @classmethod
    def do(
        cls,
        user: AbstractUser,
        node_id: int,
        new_node_type: str,
    ) -> AutomationNode:
        replacement = AutomationNodeService().replace_node(user, node_id, new_node_type)
        replaced_node = replacement.node
        cls.register_action(
            user=user,
            params=cls.Params(
                replaced_node.workflow.automation.id,
                replaced_node.workflow.automation.name,
                replaced_node.workflow_id,
                replaced_node.id,
                replaced_node.get_type().type,
                replacement.original_node_id,
                replacement.original_node_type,
            ),
            scope=cls.scope(replaced_node.workflow.id),
            workspace=replaced_node.workflow.automation.workspace,
        )
        return replaced_node

    @classmethod
    def scope(cls, workflow_id):
        return WorkflowActionScopeType.value(workflow_id)

    @classmethod
    def undo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_undo: Action,
    ):
        # Restore the node to its original type.
        restored_node = TrashHandler.restore_item(
            user,
            AutomationNodeTrashableItemType.type,
            params.original_node_id,
        )
        # Trash the node of the new type, and pass its operation type so that its
        # trash entry is flagged as managed to prevent users from restoring it.
        deleted_node = AutomationNodeService().delete_node(
            user,
            params.node_id,
            trash_operation_type=ReplaceAutomationNodeTrashOperationType.type,
        )
        automation_node_replaced.send(
            cls,
            workflow=restored_node.workflow,
            deleted_node=deleted_node,
            restored_node=restored_node.specific,
            user=user,
        )

    @classmethod
    def redo(
        cls,
        user: AbstractUser,
        params: Params,
        action_to_redo: Action,
    ):
        # Restore the node to its new type again.
        restored_node = TrashHandler.restore_item(
            user,
            AutomationNodeTrashableItemType.type,
            params.node_id,
        )
        # Trash the node of the original type, and pass its operation type so that its
        # trash entry is flagged as managed to prevent users from restoring it.
        deleted_node = AutomationNodeService().delete_node(
            user,
            params.original_node_id,
            trash_operation_type=ReplaceAutomationNodeTrashOperationType.type,
        )
        automation_node_replaced.send(
            cls,
            workflow=restored_node.workflow,
            restored_node=restored_node.specific,
            deleted_node=deleted_node,
            user=user,
        )
