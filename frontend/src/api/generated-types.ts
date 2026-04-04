/**
 * This file is auto-generated from docs/contracts/baseline.openapi.yaml
 * DO NOT EDIT MANUALLY — regenerate with: ./scripts/generate-contract-types.sh docs/contracts/baseline.openapi.yaml
 */

export interface paths {
  "/health": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["health_health_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["list_projects_api_v1_projects_get"];
    put?: never;
    post: operations["create_project_api_v1_projects_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["get_project_api_v1_projects__project_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project_id}/epics": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["list_epics_api_v1_projects__project_id__epics_get"];
    put?: never;
    post: operations["create_epic_api_v1_projects__project_id__epics_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project_id}/epics/{epic_id}/features": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["list_features_api_v1_projects__project_id__epics__epic_id__features_get"];
    put?: never;
    post: operations["create_feature_api_v1_projects__project_id__epics__epic_id__features_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project_id}/features/{feature_id}/tasks": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["create_task_api_v1_projects__project_id__features__feature_id__tasks_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/tasks/{task_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    delete: operations["delete_task_api_v1_tasks__task_id__delete"];
    options?: never;
    head?: never;
    patch: operations["update_task_api_v1_tasks__task_id__patch"];
    trace?: never;
  };
  "/api/v1/projects/{project_id}/board": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["get_board_api_v1_projects__project_id__board_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project_id}/import": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["import_plan_api_v1_projects__project_id__import_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/gateway/me": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["get_current_project_info_api_v1_gateway_me_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/gateway/events/{project_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["stream_events_api_v1_gateway_events__project_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agents/register": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["register_agent_api_v1_agents_register_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agents/{worktree_id}/heartbeat": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["heartbeat_api_v1_agents__worktree_id__heartbeat_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agents/{worktree_id}/tasks": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["get_tasks_api_v1_agents__worktree_id__tasks_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agents/{worktree_id}/start-task": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["start_task_api_v1_agents__worktree_id__start_task_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agents/{worktree_id}/complete-task": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["complete_task_api_v1_agents__worktree_id__complete_task_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/agents/{worktree_id}/task-status": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch: operations["update_task_status_api_v1_agents__worktree_id__task_status_patch"];
    trace?: never;
  };
  "/api/v1/agents/{worktree_id}/unregister": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["unregister_agent_api_v1_agents__worktree_id__unregister_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/projects/{project_id}/worktrees": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["list_worktrees_api_v1_projects__project_id__worktrees_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/documents": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["list_documents_api_v1_documents_get"];
    put?: never;
    post: operations["create_document_api_v1_documents_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/v1/documents/{document_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["get_document_api_v1_documents__document_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}

export type webhooks = Record<string, never>;

export interface components {
  schemas: {
    BoardColumn: {
      status: string;
      tasks: components["schemas"]["TaskCard"][];
    };
    BoardResponse: {
      /** Format: uuid */
      project_id: string;
      project_name: string;
      columns: components["schemas"]["BoardColumn"][];
      total_tasks: number;
      done_count: number;
    };
    CompleteTaskRequest: {
      /** Format: uuid */
      task_id: string;
    };
    CompleteTaskResponse: {
      /** Format: uuid */
      completed_task_id: string;
      next_task?: components["schemas"]["TaskInfo"] | null;
    };
    DocumentCreate: {
      /** @default  */
      title?: string;
      /** @default  */
      content?: string;
      /** @default other */
      doc_type?: string;
      /** @default  */
      source_path?: string;
      /** @default  */
      attached_to_type?: string;
      /** Format: uuid */
      attached_to_id?: string | null;
    };
    DocumentResponse: {
      /** Format: uuid */
      id: string;
      title: string;
      content: string;
      doc_type: string;
      source_path: string;
      attached_to_type: string;
      /** Format: uuid */
      attached_to_id: string | null;
      /** Format: date-time */
      created_at: string;
    };
    EpicCreate: {
      title: string;
      /** @default  */
      description?: string;
      /** @default  */
      bounded_context?: string;
      /** @default  */
      context_description?: string;
      /** @default 0 */
      position?: number;
    };
    EpicResponse: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      project_id: string;
      title: string;
      description: string;
      bounded_context: string;
      context_description: string;
      status: string;
      position: number;
      /** Format: date-time */
      created_at: string;
    };
    FeatureCreate: {
      title: string;
      /** @default  */
      description?: string;
      /** @default 0 */
      position?: number;
    };
    FeatureResponse: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      epic_id: string;
      title: string;
      description: string;
      status: string;
      position: number;
      /** Format: date-time */
      created_at: string;
    };
    HTTPValidationError: {
      detail?: components["schemas"]["ValidationError"][];
    };
    HeartbeatResponse: {
      status: string;
      /** Format: date-time */
      last_heartbeat: string;
    };
    ImportEpic: {
      title: string;
      /** @default  */
      description?: string;
      /** @default  */
      bounded_context?: string;
      /** @default [] */
      features?: components["schemas"]["ImportFeature"][];
    };
    ImportFeature: {
      title: string;
      /** @default  */
      description?: string;
      /** @default [] */
      tasks?: components["schemas"]["ImportTask"][];
    };
    ImportPlan: {
      epics: components["schemas"]["ImportEpic"][];
    };
    ImportTask: {
      title: string;
      /** @default  */
      description?: string;
      /** @default normal */
      priority?: string;
    };
    ProjectCreate: {
      name: string;
      /** @default  */
      description?: string;
      /** @default  */
      repo_url?: string;
    };
    ProjectResponse: {
      /** Format: uuid */
      id: string;
      name: string;
      description: string;
      repo_url: string;
      status: string;
      /** Format: date-time */
      created_at: string;
    };
    ProjectWithKey: {
      /** Format: uuid */
      id: string;
      name: string;
      description: string;
      repo_url: string;
      status: string;
      /** Format: date-time */
      created_at: string;
      api_key: string;
    };
    RegisterRequest: {
      worktree_path: string;
      /** @default  */
      branch_name?: string;
    };
    RegisterResponse: {
      /** Format: uuid */
      worktree_id: string;
      /** Format: uuid */
      session_id: string;
      current_task?: components["schemas"]["TaskInfo"] | null;
      /** @default false */
      resumed?: boolean;
    };
    StartTaskRequest: {
      /** Format: uuid */
      task_id: string;
    };
    StartTaskResponse: {
      /** Format: uuid */
      task_id: string;
      status: string;
    };
    /** @description Task with breadcrumb info for the Kanban board. */
    TaskCard: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      feature_id: string;
      title: string;
      description: string;
      status: string;
      priority: string;
      /** Format: uuid */
      worktree_id: string | null;
      position: number;
      /** Format: date-time */
      created_at: string;
      /** Format: date-time */
      updated_at: string;
      /** @default  */
      epic_title?: string;
      /** @default  */
      feature_title?: string;
    };
    TaskCreate: {
      title: string;
      /** @default  */
      description?: string;
      /** @default normal */
      priority?: string;
      /** @default 0 */
      position?: number;
    };
    TaskInfo: {
      /** Format: uuid */
      id: string;
      title: string;
      description: string;
      status: string;
      priority: string;
    };
    TaskResponse: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      feature_id: string;
      title: string;
      description: string;
      status: string;
      priority: string;
      /** Format: uuid */
      worktree_id: string | null;
      position: number;
      /** Format: date-time */
      created_at: string;
      /** Format: date-time */
      updated_at: string;
    };
    TaskUpdate: {
      title?: string | null;
      description?: string | null;
      status?: string | null;
      priority?: string | null;
      /** Format: uuid */
      worktree_id?: string | null;
      position?: number | null;
    };
    UpdateTaskStatusRequest: {
      /** Format: uuid */
      task_id: string;
      status: string;
    };
    ValidationError: {
      loc: (string | number)[];
      msg: string;
      type: string;
      input?: unknown;
      ctx?: Record<string, unknown>;
    };
    WorktreeResponse: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      project_id: string;
      name: string;
      worktree_path: string;
      branch_name: string;
      status: string;
      /** Format: uuid */
      current_task_id: string | null;
      /** Format: date-time */
      last_heartbeat: string | null;
      /** Format: date-time */
      created_at: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}

export type $defs = Record<string, never>;

export interface operations {
  health_health_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": Record<string, string>;
        };
      };
    };
  };
  list_projects_api_v1_projects_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["ProjectResponse"][];
        };
      };
    };
  };
  create_project_api_v1_projects_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ProjectCreate"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["ProjectWithKey"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_project_api_v1_projects__project_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["ProjectResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  create_epic_api_v1_projects__project_id__epics_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["EpicCreate"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["EpicResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_epics_api_v1_projects__project_id__epics_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["EpicResponse"][];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  create_feature_api_v1_projects__project_id__epics__epic_id__features_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
        /** Format: uuid */
        epic_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["FeatureCreate"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["FeatureResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_features_api_v1_projects__project_id__epics__epic_id__features_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
        /** Format: uuid */
        epic_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["FeatureResponse"][];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  create_task_api_v1_projects__project_id__features__feature_id__tasks_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
        /** Format: uuid */
        feature_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["TaskCreate"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["TaskResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  update_task_api_v1_tasks__task_id__patch: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        task_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["TaskUpdate"];
      };
    };
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["TaskResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  delete_task_api_v1_tasks__task_id__delete: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        task_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      204: {
        headers: Record<string, unknown>;
        content?: never;
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_board_api_v1_projects__project_id__board_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["BoardResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  import_plan_api_v1_projects__project_id__import_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ImportPlan"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": Record<string, number>;
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_current_project_info_api_v1_gateway_me_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["ProjectResponse"];
        };
      };
    };
  };
  stream_events_api_v1_gateway_events__project_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": unknown;
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  register_agent_api_v1_agents_register_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RegisterRequest"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["RegisterResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  heartbeat_api_v1_agents__worktree_id__heartbeat_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        worktree_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HeartbeatResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_tasks_api_v1_agents__worktree_id__tasks_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        worktree_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["TaskInfo"][];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  start_task_api_v1_agents__worktree_id__start_task_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        worktree_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["StartTaskRequest"];
      };
    };
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["StartTaskResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  complete_task_api_v1_agents__worktree_id__complete_task_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        worktree_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["CompleteTaskRequest"];
      };
    };
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["CompleteTaskResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  update_task_status_api_v1_agents__worktree_id__task_status_patch: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        worktree_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["UpdateTaskStatusRequest"];
      };
    };
    responses: {
      204: {
        headers: Record<string, unknown>;
        content?: never;
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  unregister_agent_api_v1_agents__worktree_id__unregister_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        worktree_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      204: {
        headers: Record<string, unknown>;
        content?: never;
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_worktrees_api_v1_projects__project_id__worktrees_get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        project_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["WorktreeResponse"][];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  create_document_api_v1_documents_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["DocumentCreate"];
      };
    };
    responses: {
      201: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["DocumentResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_documents_api_v1_documents_get: {
    parameters: {
      query?: {
        attached_to_type?: string | null;
        /** Format: uuid */
        attached_to_id?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["DocumentResponse"][];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_document_api_v1_documents__document_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        /** Format: uuid */
        document_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      200: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["DocumentResponse"];
        };
      };
      422: {
        headers: Record<string, unknown>;
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
}
