export default function PrimaryButton({text}) {
    return (
        <button className="mt-6 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
            {text}
        </button>
    )
}