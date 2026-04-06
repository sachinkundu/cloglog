import { test as base, expect } from '@playwright/test';
import { ApiHelper } from './api-helpers';

export interface SeededProject {
  projectId: string;
  projectName: string;
  apiKey: string;
  epicId: string;
  epicTitle: string;
  featureId: string;
  featureTitle: string;
  tasks: Array<{ id: string; title: string; status: string; number: number }>;
}

type TestFixtures = {
  api: ApiHelper;
  seededProject: SeededProject;
};

export const test = base.extend<TestFixtures>({
  api: async ({}, use) => {
    await use(new ApiHelper());
  },

  seededProject: async ({ api }, use) => {
    const projectName = `E2E-${Date.now()}`;
    const project = await api.createProject(projectName);
    const epic = await api.createEpic(project.id, 'Test Epic', project.api_key);
    const feature = await api.createFeature(project.id, epic.id, 'Test Feature', project.api_key);

    const backlogTask = await api.createTask(
      project.id,
      feature.id,
      'Backlog Task',
      project.api_key,
    );
    const inProgressTask = await api.createTask(
      project.id,
      feature.id,
      'Active Task',
      project.api_key,
    );
    const doneTask = await api.createTask(
      project.id,
      feature.id,
      'Completed Task',
      project.api_key,
    );

    // Move tasks to different statuses
    await api.updateTaskStatus(inProgressTask.id, 'in_progress', project.api_key);
    await api.updateTaskStatus(doneTask.id, 'in_progress', project.api_key);
    await api.updateTaskStatus(doneTask.id, 'review', project.api_key);
    await api.updateTaskStatus(doneTask.id, 'done', project.api_key);

    await use({
      projectId: project.id,
      projectName,
      apiKey: project.api_key,
      epicId: epic.id,
      epicTitle: 'Test Epic',
      featureId: feature.id,
      featureTitle: 'Test Feature',
      tasks: [
        { ...backlogTask, status: 'backlog' },
        { ...inProgressTask, status: 'in_progress' },
        { ...doneTask, status: 'done' },
      ],
    });
  },
});

export { expect };
