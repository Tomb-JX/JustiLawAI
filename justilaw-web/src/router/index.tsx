import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from '@/components/layout/app-layout'
import { PageLoading } from '@/components/common/misc'
import { RequireAdmin } from '@/features/auth/require-auth'
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
const DiscretionPage = lazy(() => import('@/features/discretion/discretion-page'))
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
    // 鉴权门控在 AppLayout 的内容区内（RequireAuth 包住 Outlet）：
    // 刷新时外壳即时渲染，加载/跳转只发生在局部，不再整页卸载重挂
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: 'chat/:conversationId?', element: page(<ChatPage />) },
      { path: 'agents', element: page(<AgentsPage />) },
      { path: 'agents/create', element: page(<CreateAgentPage />) },
      { path: 'agents/:agentId/edit', element: page(<CreateAgentPage />) },
      { path: 'agents/:agentId', element: page(<AgentDetailPage />) },
      { path: 'datasets', element: page(<DatasetsPage />) },
      { path: 'datasets/:datasetId', element: page(<DatasetDetailPage />) },
      { path: 'prompts', element: page(<PromptsPage />) },
      { path: 'models', element: page(<ModelsPage />) },
      { path: 'providers', element: page(<ProvidersPage />) },
      { path: 'workflows', element: page(<WorkflowsPage />) },
      { path: 'workflows/:id/edit', element: page(<WorkflowEditorPage />) },
      { path: 'discretion', element: page(<DiscretionPage />) },
      { path: 'admin', element: <RequireAdmin>{page(<AdminPage />)}</RequireAdmin> },
      { path: '*', element: page(<NotFound />) },
    ],
  },
])
