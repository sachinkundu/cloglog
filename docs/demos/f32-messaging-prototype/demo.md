# F-32: Cross-Session Agent Messaging Prototype

*2026-04-08T08:02:53Z by Showboat 0.6.1*
<!-- showboat-id: 4c0dfde1-78b4-4039-8d4b-466f0c266807 -->

Prototype validates heartbeat piggyback as the messaging mechanism. sendLoggingMessage (MCP SDK) does NOT surface in Claude Code. Messages are stored in agent_messages DB table, returned via heartbeat, and drained into tool responses.

```bash
PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d cloglog -c "\d agent_messages" 2>&1 | head -15
```

```output
                                Table "public.agent_messages"
    Column    |           Type           | Collation | Nullable |           Default           
--------------+--------------------------+-----------+----------+-----------------------------
 id           | uuid                     |           | not null | gen_random_uuid()
 worktree_id  | uuid                     |           | not null | 
 message      | text                     |           | not null | 
 sender       | character varying(100)   |           | not null | 'system'::character varying
 delivered    | boolean                  |           | not null | false
 created_at   | timestamp with time zone |           | not null | now()
 delivered_at | timestamp with time zone |           |          | 
Indexes:
    "agent_messages_pkey" PRIMARY KEY, btree (id)
    "ix_agent_messages_pending" btree (worktree_id, delivered)
Foreign-key constraints:
    "agent_messages_worktree_id_fkey" FOREIGN KEY (worktree_id) REFERENCES worktrees(id)
```

```bash
PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d cloglog -c "SELECT sender, delivered, LEFT(message, 60) AS message, delivered_at FROM agent_messages ORDER BY created_at DESC LIMIT 5" 2>&1
```

```output
                sender                | delivered |                           message                            |         delivered_at          
--------------------------------------+-----------+--------------------------------------------------------------+-------------------------------
 e437ffb0-f669-4744-a94f-9fce9d478f04 | t         | Test message: if you see this in a tool response, heartbeat  | 2026-04-08 07:44:16.703271+00
(1 row)

```

The test message was delivered=true with a delivered_at timestamp, confirming the full DB-backed flow works end-to-end.
