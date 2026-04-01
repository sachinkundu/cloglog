#!/usr/bin/env node

/**
 * cloglog-mcp: MCP server for agent ↔ cloglog communication.
 * Tools are implemented in Phase 1-3.
 */

import { CloglogClient } from './client.js'

const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8000'
const CLOGLOG_API_KEY = process.env.CLOGLOG_API_KEY ?? ''

const client = new CloglogClient({
  baseUrl: CLOGLOG_URL,
  apiKey: CLOGLOG_API_KEY,
})

// MCP server setup will be added in Phase 1
console.error('cloglog-mcp: server stub loaded')

export { client }
