import { test as base, expect } from '@playwright/test';
import { ApiHelper } from './api-helpers';

export interface SeededProject {
  projectId: string;
  projectName: string;
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
    const epic = await api.createEpic(project.id, 'Test Epic');
    const feature = await api.createFeature(project.id, epic.id, 'Test Feature');

    const backlogTask = await api.createTask(project.id, feature.id, 'Backlog Task');
    const inProgressTask = await api.createTask(project.id, feature.id, 'Active Task');
    const doneTask = await api.createTask(project.id, feature.id, 'Completed Task');

    // Move tasks to different statuses
    await api.updateTaskStatus(inProgressTask.id, 'in_progress');
    await api.updateTaskStatus(doneTask.id, 'in_progress');
    await api.updateTaskStatus(doneTask.id, 'review');
    await api.updateTaskStatus(doneTask.id, 'done');

    await use({
      projectId: project.id,
      projectName,
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
