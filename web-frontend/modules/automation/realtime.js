import { generateHash } from '@baserow/modules/core/utils/hashing'

export const registerRealtimeEvents = (realtime) => {
  // Workflow events
  realtime.registerEvent('automation_workflow_created', ({ store }, data) => {
    const automation = store.getters['application/get'](
      data.workflow.automation_id
    )
    store.dispatch('automationWorkflow/forceCreate', {
      automation,
      workflow: data.workflow,
    })
  })

  realtime.registerEvent('automation_workflow_deleted', ({ store }, data) => {
    const automation = store.getters['application/get'](data.automation_id)
    if (automation !== undefined) {
      const workflow = store.getters['automationWorkflow/getWorkflows'](
        automation
      ).find((w) => w.id === data.workflow_id)
      if (workflow !== undefined) {
        store.dispatch('automationWorkflow/forceDelete', {
          automation,
          workflow,
        })
      }
    }
  })

  realtime.registerEvent('automation_workflow_updated', ({ store }, data) => {
    const automation = store.getters['application/get'](
      data.workflow.automation_id
    )
    if (automation !== undefined) {
      const workflow = store.getters['automationWorkflow/getWorkflows'](
        automation
      ).find((w) => w.id === data.workflow.id)
      if (workflow !== undefined) {
        store.dispatch('automationWorkflow/forceUpdate', {
          automation,
          workflow,
          values: data.workflow,
        })
      }
    }
  })

  realtime.registerEvent('automation_workflow_published', ({ store }, data) => {
    const automation = store.getters['application/get'](
      data.workflow.automation_id
    )
    if (automation !== undefined) {
      const workflow = store.getters['automationWorkflow/getWorkflows'](
        automation
      ).find((w) => w.id === data.workflow.id)
      if (workflow !== undefined) {
        store.dispatch('automationWorkflow/forceUpdate', {
          automation,
          workflow,
          values: data.workflow,
        })
      }
    }
  })

  realtime.registerEvent(
    'automation_workflows_reordered',
    ({ store, app }, data) => {
      const automation = store.getters['application/getAll'].find(
        (application) => generateHash(application.id) === data.automation_id
      )
      if (automation !== undefined) {
        store.commit('automationWorkflow/ORDER_WORKFLOWS', {
          automation,
          order: data.order,
          isHashed: true,
        })
      }
    }
  )

  // Workflow node events
  realtime.registerEvent('automation_node_created', ({ store }, data) => {
    const workflow = store.getters['automationWorkflow/getSelected']
    if (workflow && workflow.id === data.node.workflow) {
      store.dispatch('automationWorkflowNode/forceCreate', {
        workflow,
        node: data.node,
      })
    }
  })

  realtime.registerEvent('automation_node_updated', ({ store }, data) => {
    const workflow = store.getters['automationWorkflow/getSelected']
    const node = data.node
    if (!workflow || !node) return
    if (workflow.id !== (node.workflow || node.workflow_id)) return

    const existing = store.getters['automationWorkflowNode/findById'](
      workflow,
      node.id
    )
    if (!existing) return

    store.dispatch('automationWorkflowNode/forceUpdate', {
      workflow,
      node: existing,
      values: node,
      override: true,
    })
  })

  realtime.registerEvent('automation_nodes_updated', ({ store }, data) => {
    const { workflow_id: workflowId, nodes } = data
    const workflow = store.getters['automationWorkflow/getSelected']
    if (!workflow || workflow.id !== workflowId) return
    nodes.forEach((node) => {
      const existing = store.getters['automationWorkflowNode/findById'](
        workflow,
        node.id
      )
      store.dispatch('automationWorkflowNode/forceUpdate', {
        workflow,
        node: existing,
        values: node,
        override: true,
      })
    })
  })

  realtime.registerEvent('automation_node_replaced', ({ store }, data) => {
    const {
      workflow_id: workflowId,
      deleted_node: deletedNode,
      restored_node: restoredNode,
    } = data

    const workflow = store.getters['automationWorkflow/getSelected']
    if (workflow.id !== workflowId) return

    // Find the nodes that follow the node we're about to delete.
    const deletedNodeNextNodes = store.getters[
      'automationWorkflowNode/getNextNodes'
    ](workflow, deletedNode)

    // Add our new node.
    store.dispatch('automationWorkflowNode/forceCreate', {
      workflow,
      node: restoredNode,
    })

    // Update the deleted node's next nodes,
    // so they point to the newly added node.
    deletedNodeNextNodes.forEach((nextNode) => {
      store.dispatch('automationWorkflowNode/forceUpdate', {
        workflow,
        node: nextNode,
        values: { previous_node_id: restoredNode.id },
      })
    })

    // Now delete the old node.
    store.dispatch('automationWorkflowNode/forceDelete', {
      workflow,
      nodeId: deletedNode.id,
    })
  })

  realtime.registerEvent('automation_node_deleted', ({ store }, data) => {
    const workflow = store.getters['automationWorkflow/getSelected']
    const nodeId = data.node_id || data.node?.id
    const workflowId = data.workflow || data.workflow_id || data.node?.workflow
    if (!workflow || !nodeId) return
    if (workflowId && workflow.id !== workflowId) return

    store.dispatch('automationWorkflowNode/forceDelete', {
      workflow,
      nodeId,
    })
  })
}
