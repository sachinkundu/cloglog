// Demo harness: invoke the MCP `update_task_status` tool with a mocked
// HTTP client and print the exact guidance string the agent will see.
//
// Run `npm run build` first so `dist/server.js` exists.

import { createServer } from '../dist/server.js'

// The `register_agent` tool stores the `worktree_id` returned by the backend
// on the server instance and subsequent tools require it. Return a stable
// fake so the mocked harness behaves like a registered agent.
const mockClient = {
  request: async (method, path) => {
    if (path === '/api/v1/agents/register') {
      return {
        worktree_id: 'demo-worktree',
        project_id: 'demo-project',
        agent_token: 'demo-token',
      }
    }
    return {}
  },
  registerAgent: async () => ({}),
  setAgentToken: () => {},
  clearAgentToken: () => {},
}

const server = createServer(mockClient)
const tools = server._registeredTools

// Register first so the tool has a worktree context.
await tools.register_agent.handler({
  worktree_path: '/tmp/demo-worktree',
})

const result = await tools.update_task_status.handler({
  task_id: 'demo-task-id',
  status: 'review',
  pr_url: 'https://github.com/sachinkundu/cloglog/pull/99',
})

console.log(result.content[0].text)

// Exit immediately — createServer starts a heartbeat timer (setInterval) that
// keeps the Node event loop alive. For this one-shot demo we don't need to
// unregister; just hard-exit once the guidance string is printed.
process.exit(0)
