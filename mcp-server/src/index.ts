#!/usr/bin/env node

/**
 * cloglog-mcp: MCP server for agent <-> cloglog communication.
 * Runs on stdio, providing tools for agent registration and task management.
 */

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CloglogClient } from './client.js'
import { loadApiKey, MissingCredentialsError } from './credentials.js'
import { createServer } from './server.js'

const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://127.0.0.1:8001'
const MCP_SERVICE_KEY = process.env.MCP_SERVICE_KEY ?? 'cloglog-mcp-dev'

let CLOGLOG_API_KEY: string
try {
  CLOGLOG_API_KEY = loadApiKey()
} catch (err) {
  if (err instanceof MissingCredentialsError) {
    console.error(err.message)
    process.exit(78) // EX_CONFIG: configuration error
  }
  throw err
}

const client = new CloglogClient({
  baseUrl: CLOGLOG_URL,
  apiKey: CLOGLOG_API_KEY,
  serviceKey: MCP_SERVICE_KEY,
})

const server = createServer(client)
const transport = new StdioServerTransport()

await server.connect(transport)
console.error('cloglog-mcp: server started on stdio')
