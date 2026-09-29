export default function DashboardPanel({ children, className = "" }) {
    return (
        <div
            className={`flex min-h-[280px] min-w-0 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white p-4 shadow-sm ${className}`}
        >
            {children}
        </div>
    );
}