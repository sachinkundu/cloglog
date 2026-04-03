#!/usr/bin/env node

/**
 * cloglog-mcp: MCP server for agent <-> cloglog communication.
 * Runs on stdio, providing tools for agent registration and task management.
 */

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CloglogClient } from './client.js'
import { createServer } from './server.js'

const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8000'
const CLOGLOG_API_KEY = process.env.CLOGLOG_API_KEY ?? ''

const client = new CloglogClient({
  baseUrl: CLOGLOG_URL,
  apiKey: CLOGLOG_API_KEY,
})

const server = createServer(client)
const transport = new StdioServerTransport()

await server.connect(transport)
console.error('cloglog-mcp: server started on stdio')
