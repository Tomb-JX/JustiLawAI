import { cn } from '@/lib/utils'

/** 骨架屏：渐变扫光（.skeleton-shimmer，reduced-motion 下自动静止） */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('skeleton-shimmer rounded-lg', className)} {...props} />
}

export { Skeleton }
