export default function StatusInfo({status}) {
  return (
    <div className="space-y-4">
    {status !== null ? (
        Object.entries(status).map(([key, val]) => (
            <div key={key} className="flex justify-between items-center border-b border-gray-200 pb-3 last:border-b-0">
            <label className="text-sm font-medium text-gray-700 capitalize">
                {key.replace(/_/g, ' ')}
            </label>
            <span className="text-gray-900 font-medium">
                {String(val)}
            </span>
            </div>
        ))
    ) : (<></>)}
    </div>
  );
}