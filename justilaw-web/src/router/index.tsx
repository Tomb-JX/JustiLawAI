import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from '@/components/layout/app-layout'
import { PageLoading } from '@/components/common/misc'
import { RequireAuth } from '@/features/auth/require-auth'
import { CALLBACK_PATH } from '@/features/auth/logto-config'

const ChatPage = lazy(() => import('@/features/chat/chat-page'))
const AgentsPage = lazy(() => import('@/features/agents/agents-page'))
const AgentDetailPage = lazy(() => import('@/features/agents/agent-detail-page'))
const CreateAgentPage = lazy(() => import('@/features/agents/create-agent-page'))
const DatasetsPage = lazy(() => import('@/features/datasets/datasets-page'))
const DatasetDetailPage = lazy(() => import('@/features/datasets/dataset-detail-page'))
const PromptsPage = lazy(() => import('@/features/prompts/prompts-page'))
const ModelsPage = lazy(() => import('@/features/models/models-page'))
const ProvidersPage = lazy(() => import('@/features/models/providers-page'))
const WorkflowsPage = lazy(() => import('@/features/workflows/workflows-page'))
const WorkflowEditorPage = lazy(() => import('@/features/workflows/workflow-editor-page'))
const AdminPage = lazy(() => import('@/features/admin/admin-page'))
const NotFound = lazy(() => import('@/features/misc/not-found'))
const LoginPage = lazy(() => import('@/features/auth/login-page'))
const CallbackPage = lazy(() => import('@/features/auth/callback-page'))

const page = (el: React.ReactNode) => <Suspense fallback={<PageLoading />}>{el}</Suspense>

export const router = createBrowserRouter([
  { path: '/login', element: page(<LoginPage />) },
  { path: CALLBACK_PATH, element: page(<CallbackPage />) },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: 'chat/:conversationId?', element: page(<ChatPage />) },
      { path: 'agents', element: page(<AgentsPage />) },
      { path: 'agents/create', element: page(<CreateAgentPage />) },
      { path: 'agents/:agentId', element: page(<AgentDetailPage />) },
      { path: 'datasets', element: page(<DatasetsPage />) },
      { path: 'datasets/:datasetId', element: page(<DatasetDetailPage />) },
      { path: 'prompts', element: page(<PromptsPage />) },
      { path: 'models', element: page(<ModelsPage />) },
      { path: 'providers', element: page(<ProvidersPage />) },
      { path: 'workflows', element: page(<WorkflowsPage />) },
      { path: 'workflows/:id/edit', element: page(<WorkflowEditorPage />) },
      { path: 'admin', element: page(<AdminPage />) },
      { path: '*', element: page(<NotFound />) },
    ],
  },
])
