import { test, expect } from '../fixtures/test-fixtures';

test.describe('Detail Panel', () => {
  test('task detail shows title, status, and description', async ({ page, seededProject, api }) => {
    // Create task with a description
    const task = await api.createTask(
      seededProject.projectId,
      seededProject.featureId,
      'Described Task',
      'This is a test description',
    );

    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page.locator('.detail-title')).toContainText('Described Task');
    await expect(page.locator('.detail-status')).toBeVisible();
    await expect(page.locator('.detail-description')).toContainText('This is a test description');
  });

  test('task description renders markdown', async ({ page, seededProject, api }) => {
    const task = await api.createTask(
      seededProject.projectId,
      seededProject.featureId,
      'Markdown Task',
      '**bold text** and `code`',
    );

    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-description strong')).toHaveText('bold text');
    await expect(page.locator('.detail-description code')).toHaveText('code');
  });

  test('task detail shows breadcrumb pills', async ({ page, seededProject }) => {
    const task = seededProject.tasks[0];
    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-panel .breadcrumb-pills')).toBeVisible();
    await expect(page.locator('.detail-panel .pill')).toHaveCount(2);
  });

  test('epic detail shows progress bar and feature list', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}/epics/${seededProject.epicId}`);
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page.locator('.detail-title')).toContainText(seededProject.epicTitle);
    await expect(page.locator('.detail-progress')).toBeVisible();
    // Feature list section
    await expect(page.locator('.detail-list-item', { hasText: seededProject.featureTitle })).toBeVisible();
  });

  test('feature detail shows task list and parent epic pill', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}/features/${seededProject.featureId}`);
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page.locator('.detail-title')).toContainText(seededProject.featureTitle);
    // Parent epic pill
    await expect(page.locator('.detail-parent-pill')).toContainText(seededProject.epicTitle);
    // Task list
    await expect(page.locator('.detail-list-item')).toHaveCount(3); // 3 seeded tasks
  });

  test('panel closes on overlay click', async ({ page, seededProject }) => {
    const task = seededProject.tasks[0];
    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-panel')).toBeVisible();

    // Click the overlay (not the panel itself)
    await page.locator('[data-testid="detail-overlay"]').click({ position: { x: 10, y: 10 } });
    await expect(page.locator('.detail-panel')).not.toBeVisible();
  });

  test('panel closes on close button', async ({ page, seededProject }) => {
    const task = seededProject.tasks[0];
    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-panel')).toBeVisible();

    await page.locator('.detail-close').click();
    await expect(page.locator('.detail-panel')).not.toBeVisible();
  });

  test('navigation: click epic pill in task → epic detail', async ({ page, seededProject }) => {
    const task = seededProject.tasks[0];
    await page.goto(`/projects/${seededProject.projectId}/tasks/${task.id}`);
    await expect(page.locator('.detail-panel')).toBeVisible();

    // Click the epic pill in breadcrumbs
    await page.locator('.detail-panel .pill-epic').click();
    await expect(page).toHaveURL(new RegExp(`/epics/${seededProject.epicId}`));
    await expect(page.locator('.detail-title')).toContainText(seededProject.epicTitle);
  });
});
