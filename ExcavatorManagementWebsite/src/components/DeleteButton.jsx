export default function DeleteButton({text, onClick}) {
    return (
        <button type="button" onClick={onClick} className="mt-6 px-4 py-2 bg-red-700 text-white rounded-lg hover:bg-blue-800 transition">
            {text}
        </button>
    )
}