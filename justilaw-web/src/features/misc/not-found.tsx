import { Link } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'

export default function NotFound() {
  return (
    <div className="flex h-full flex-col items-center justify-center">
      <div className="text-6xl font-bold text-muted-foreground/30">404</div>
      <p className="mt-3 text-sm text-muted-foreground">页面不存在或已被移动</p>
      <Link to="/chat" className={`${buttonVariants({ variant: 'outline' })} mt-5`}>
        返回对话
      </Link>
    </div>
  )
}
