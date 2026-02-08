export default function FormLblInGroup({inputType, labelText, inputValue, onInputChanged}) {
    return (
    <div className="flex flex-col">
        <label className="text-sm font-medium text-gray-700 mb-1 capitalize">
        {labelText}
        </label>
        <input
        type={inputType}
        value={inputValue}
        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        onChange={onInputChanged}
        />
    </div>
    )
}