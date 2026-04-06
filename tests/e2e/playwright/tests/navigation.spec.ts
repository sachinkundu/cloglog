import { test, expect } from '../fixtures/test-fixtures';

test.describe('Navigation', () => {
  test('redirects / to /projects', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/projects/);
  });

  test('project selector shows projects', async ({ page, seededProject }) => {
    await page.goto('/projects');
    await expect(page.getByText(seededProject.projectName)).toBeVisible();
  });

  test('clicking project navigates to board', async ({ page, seededProject }) => {
    await page.goto('/projects');
    await page.getByText(seededProject.projectName).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${seededProject.projectId}`));
  });

  test('direct URL to task opens detail panel', async ({ page, seededProject }) => {
    const task = seededProject.tasks[0];
    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page.locator('.detail-title')).toContainText(task.title);
  });

  test('browser back/forward navigation', async ({ page, seededProject }) => {
    // Navigate to board
    await page.goto(`/projects/${seededProject.projectId}`);
    await expect(page).toHaveURL(new RegExp(`/projects/${seededProject.projectId}`));

    // Click a task to open detail panel
    const task = seededProject.tasks[1]; // Active Task (in_progress)
    await page.locator('.task-card', { hasText: task.title }).click();
    await expect(page).toHaveURL(new RegExp(`/tasks/${task.id}`));

    // Go back
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`/projects/${seededProject.projectId}$`));

    // Go forward
    await page.goForward();
    await expect(page).toHaveURL(new RegExp(`/tasks/${task.id}`));
  });

  test('page refresh preserves state', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);
    await page.reload();
    // Board should still be visible after refresh
    await expect(page.locator('.column-title', { hasText: 'In Progress' })).toBeVisible();
  });
});
