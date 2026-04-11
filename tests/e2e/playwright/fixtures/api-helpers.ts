const API_BASE = process.env.E2E_API_BASE ?? 'http://localhost:8001/api/v1';
const DASHBOARD_KEY = process.env.E2E_DASHBOARD_KEY ?? 'cloglog-dashboard-dev';

interface ProjectResponse {
  id: string;
  name: string;
  api_key: string;
}

interface EpicResponse {
  id: string;
  title: string;
  number: number;
  color: string;
}

interface FeatureResponse {
  id: string;
  title: string;
  number: number;
}

interface TaskResponse {
  id: string;
  title: string;
  number: number;
  status: string;
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { headers, ...rest } = options;
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: { 'Content-Type': 'application/json', 'X-Dashboard-Key': DASHBOARD_KEY, ...(headers as Record<string, string>) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${options.method ?? 'GET'} ${path} failed (${res.status}): ${body}`);
  }
  return res.json() as Promise<T>;
}

function authHeaders(apiKey: string): Record<string, string> {
  return { Authorization: `Bearer ${apiKey}` };
}

export class ApiHelper {
  async createProject(name: string): Promise<ProjectResponse> {
    return apiFetch<ProjectResponse>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async createEpic(projectId: string, title: string, apiKey: string): Promise<EpicResponse> {
    return apiFetch<EpicResponse>(`/projects/${projectId}/epics`, {
      method: 'POST',
      body: JSON.stringify({ title }),
      headers: authHeaders(apiKey),
    });
  }

  async createFeature(
    projectId: string,
    epicId: string,
    title: string,
    apiKey: string,
  ): Promise<FeatureResponse> {
    return apiFetch<FeatureResponse>(`/projects/${projectId}/epics/${epicId}/features`, {
      method: 'POST',
      body: JSON.stringify({ title }),
      headers: authHeaders(apiKey),
    });
  }

  async createTask(
    projectId: string,
    featureId: string,
    title: string,
    apiKey: string,
    description?: string,
  ): Promise<TaskResponse> {
    return apiFetch<TaskResponse>(`/projects/${projectId}/features/${featureId}/tasks`, {
      method: 'POST',
      body: JSON.stringify({ title, description: description ?? '' }),
      headers: authHeaders(apiKey),
    });
  }

  async updateTaskStatus(taskId: string, status: string, apiKey: string): Promise<TaskResponse> {
    return apiFetch<TaskResponse>(`/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
      headers: authHeaders(apiKey),
    });
  }

  async deleteTask(taskId: string, apiKey: string): Promise<void> {
    await fetch(`${API_BASE}/tasks/${taskId}`, {
      method: 'DELETE',
      headers: authHeaders(apiKey),
    });
  }
}
