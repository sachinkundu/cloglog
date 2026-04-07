# T-126: Fix agent task count — exclude done/archived

*2026-04-07T16:36:25Z by Showboat 0.6.1*
<!-- showboat-id: a436db21-f75d-4e8f-9d96-7757f1fad8d3 -->

Agent task counts now exclude done and archived tasks. Only active tasks (backlog, in_progress, review) are counted.

```bash {image}
![Sidebar with corrected active task counts](docs/demos/t126-fix-agent-count/sidebar-fixed-counts.png)
```

![Sidebar with corrected active task counts](90750d01-2026-04-07.png)

Each agent shows only its active task count. Previously done/archived tasks inflated the number.
