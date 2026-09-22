export default function StepIndicator({ message }: { message: string }) {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
        <span className="h-2 w-2 animate-pulse rounded-full bg-sky-500" />
        <span>{message}</span>
      </div>
    </div>
  )
}
