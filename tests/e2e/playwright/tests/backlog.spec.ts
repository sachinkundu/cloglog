import { test, expect } from '../fixtures/test-fixtures';

test.describe('Backlog Tree', () => {
  test('renders epic > feature > task hierarchy', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    // Epic header visible
    const epic = page.locator('.backlog-epic');
    await expect(epic).toBeVisible();
    await expect(epic.locator('.backlog-epic-title')).toContainText(seededProject.epicTitle);

    // Feature nested under epic
    const feature = epic.locator('.backlog-feature');
    await expect(feature).toBeVisible();
    await expect(feature.locator('.backlog-feature-title')).toContainText(seededProject.featureTitle);

    // Backlog task nested under feature
    const task = feature.locator('.backlog-task');
    await expect(task).toBeVisible();
    await expect(task).toContainText('Backlog Task');
  });

  test('epics show colored border and progress counts', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const epicHeader = page.locator('.backlog-epic-header').first();
    // Epic has colored left border
    await expect(epicHeader).toHaveCSS('border-left-style', 'solid');

    // Progress bar exists
    await expect(page.locator('.backlog-epic .seg-progress').first()).toBeVisible();
  });

  test('expand/collapse epics', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const epic = page.locator('.backlog-epic').first();
    const toggle = epic.locator('.backlog-toggle').first();
    const feature = epic.locator('.backlog-feature');

    // Initially expanded - feature visible
    await expect(feature).toBeVisible();

    // Collapse epic
    await toggle.click();
    await expect(feature).not.toBeVisible();

    // Expand again
    await toggle.click();
    await expect(feature).toBeVisible();
  });

  test('expand/collapse features', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const feature = page.locator('.backlog-feature').first();
    const toggle = feature.locator('.backlog-toggle').first();
    const tasks = feature.locator('.backlog-task');

    // Initially expanded - task visible
    await expect(tasks.first()).toBeVisible();

    // Collapse feature
    await toggle.click();
    await expect(tasks.first()).not.toBeVisible();

    // Expand again
    await toggle.click();
    await expect(tasks.first()).toBeVisible();
  });

  test('show completed toggle', async ({ page, seededProject, api }) => {
    // Create a feature where all tasks are done
    const epic2 = await api.createEpic(seededProject.projectId, 'Done Epic', seededProject.apiKey);
    const feat2 = await api.createFeature(seededProject.projectId, epic2.id, 'Done Feature', seededProject.apiKey);
    const task = await api.createTask(seededProject.projectId, feat2.id, 'Done Task', seededProject.apiKey);
    await api.updateTaskStatus(task.id, 'in_progress', seededProject.apiKey);
    await api.updateTaskStatus(task.id, 'review', seededProject.apiKey);
    await api.updateTaskStatus(task.id, 'done', seededProject.apiKey);

    await page.goto(`/projects/${seededProject.projectId}`);

    const completedToggle = page.locator('.backlog-completed-toggle');
    // If toggle exists, completed items are hidden by default
    if (await completedToggle.isVisible()) {
      // Click to show completed
      await completedToggle.click();
      await expect(page.locator('.backlog-epic', { hasText: 'Done Epic' })).toBeVisible();

      // Click to hide again
      await completedToggle.click();
      await expect(page.locator('.backlog-epic', { hasText: 'Done Epic' })).not.toBeVisible();
    }
  });

  test('clicking backlog task opens detail panel', async ({ page, seededProject }) => {
    await page.goto(`/projects/${seededProject.projectId}`);

    const backlogTask = seededProject.tasks.find(t => t.status === 'backlog')!;
    await page.locator('.backlog-task', { hasText: 'Backlog Task' }).click();
    await expect(page.locator('.detail-panel')).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/tasks/${backlogTask.id}`));
  });
});
