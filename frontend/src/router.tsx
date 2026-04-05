import { createBrowserRouter, Navigate } from 'react-router-dom'
import App from './App'

export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/projects" replace /> },
  { path: '/projects', element: <App /> },
  { path: '/projects/:projectId', element: <App /> },
  { path: '/projects/:projectId/dependencies', element: <App /> },
  { path: '/projects/:projectId/epics/:epicId', element: <App /> },
  { path: '/projects/:projectId/features/:featureId', element: <App /> },
  { path: '/projects/:projectId/tasks/:taskId', element: <App /> },
])
