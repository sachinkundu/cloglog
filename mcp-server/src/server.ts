import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { z } from 'zod'
import { CloglogClient } from './client.js'

export function createServer(client: CloglogClient): McpServer {
  const server = new McpServer({
    name: 'cloglog-mcp',
    version: '0.1.0',
  })

  server.tool(
    'register_agent',
    'Register this worktree with cloglog. Called at session start. Returns current task if resuming.',
    { worktree_path: z.string().describe('Absolute path to the git worktree') },
    async ({ worktree_path }) => {
      try {
        const result = await client.registerAgent(worktree_path)
        return {
          content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }],
        }
      } catch (err) {
        return {
          isError: true,
          content: [{ type: 'text' as const, text: (err as Error).message }],
        }
      }
    },
  )

  return server
}
