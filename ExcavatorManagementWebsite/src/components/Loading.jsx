
export default function Loading() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 animate-spin-container">
        <img className="spin-excavator w-32 h-32" src="/vite.svg" />
      <p className="text-gray-600 font-medium"></p>
    </div>
  );
}