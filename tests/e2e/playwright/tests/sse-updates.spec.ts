import { test, expect } from '../fixtures/test-fixtures';

test.describe('SSE Live Updates', () => {
  test('new task appears without refresh', async ({ page, seededProject, api }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    // Wait for board to fully load
    await expect(page.locator('.backlog-task', { hasText: 'Backlog Task' })).toBeVisible();

    // Create a new task via API — should appear via SSE
    await api.createTask(
      seededProject.projectId,
      seededProject.featureId,
      'SSE New Task',
      seededProject.apiKey,
    );

    // Should appear in backlog without refresh
    await expect(page.locator('.backlog-task', { hasText: 'SSE New Task' })).toBeVisible({
      timeout: 10_000,
    });
  });

  test('task status change moves card between columns', async ({ page, seededProject, api }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    const backlogTask = seededProject.tasks.find(t => t.status === 'backlog')!;

    // Backlog task is in backlog tree
    await expect(page.locator('.backlog-task', { hasText: 'Backlog Task' })).toBeVisible();

    // Move it to in_progress via API
    await api.updateTaskStatus(backlogTask.id, 'in_progress', seededProject.apiKey);

    // Should move to In Progress column
    const inProgressCol = page.locator('.column').filter({
      has: page.locator('.column-title', { hasText: 'In Progress' }),
    });
    await expect(inProgressCol.locator('.task-card', { hasText: 'Backlog Task' })).toBeVisible({
      timeout: 10_000,
    });
  });

  test('task deletion removes card', async ({ page, seededProject, api }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    const backlogTask = seededProject.tasks.find(t => t.status === 'backlog')!;

    await expect(page.locator('.backlog-task', { hasText: 'Backlog Task' })).toBeVisible();

    // Delete via API
    await api.deleteTask(backlogTask.id, seededProject.apiKey);

    // Should disappear
    await expect(page.locator('.backlog-task', { hasText: 'Backlog Task' })).not.toBeVisible({
      timeout: 10_000,
    });
  });

  test('new epic appears in backlog', async ({ page, seededProject, api }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    await expect(page.locator('.backlog-epic')).toBeVisible();

    // Create new epic via API
    await api.createEpic(seededProject.projectId, 'SSE New Epic', seededProject.apiKey);

    // Should appear in backlog tree
    await expect(page.locator('.backlog-epic-title', { hasText: 'SSE New Epic' })).toBeVisible({
      timeout: 10_000,
    });
  });
});
