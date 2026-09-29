export default function StatusIndicator({active, onMsg, offMsg}) {
        return (
            <div className="flex items-center gap-2">
            <span
                className={`inline-block w-3 h-3 rounded-full ${
                active ? "bg-green-500 animate-pulse" : "bg-red-500"
                }`}
            ></span>
            <span className="text-sm font-medium">
                {active ? onMsg : offMsg}
            </span>
            </div>
        );
    }