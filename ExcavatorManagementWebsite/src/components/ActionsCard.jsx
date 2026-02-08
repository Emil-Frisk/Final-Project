import Loading from "./Loading"
import AddPwmChannelForm from "./AddPwmChannelForm"

export default function ActionsCard({loading, onStartScreen, onStopScreen, showAddPwmChannelForm, onShowAddPwmChannelForm, onAddPwmChannel}) {
    return (
        loading ? (<Loading /> ) : 
        showAddPwmChannelForm ? (
            <AddPwmChannelForm onAddPwmChannel={onAddPwmChannel} onShowAddPwmChannelForm={onShowAddPwmChannelForm} />
        ) :
         (<div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
            <div className="bg-white rounded-lg shadow-md p-8 w-full max-w-md">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">
                Excavator Actions
            </h2>
            <div className="flex flex-col gap-3">
                <div className="border border-gray-200 rounded-lg p-6">
                    <button onClick={onStartScreen} className="w-full px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition mb-3">
                    Start Screen
                    </button>
                    <button onClick={onStopScreen} className="w-full px-4 py-2 bg-red-700 text-white rounded-lg hover:bg-red-800 transition">
                    Stop Screen
                    </button>
                </div>
                <div onClick={() => onShowAddPwmChannelForm(true)} className="border border-gray-200 rounded-lg p-6">
                    <button className="w-full px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition">
                        Add PWM Channel
                    </button>
                </div>
            </div>
            </div>
        </div>
        )
    )
}