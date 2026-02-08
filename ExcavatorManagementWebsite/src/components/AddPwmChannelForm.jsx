import Loading from "./Loading"
import { useState } from 'react';

export default function AddPwmChannelForm({loading, onAddPwmChannel, onShowAddPwmChannelForm}) {
    const [config, setConfig]= useState(null);

    const handleInputChange = (e, key) => {
        const { value, type, checked } = e.target;
        const inputValue = type === "checkbox" ? checked : value;
        setConfig(prev => ({ ...prev, [key]: inputValue }));
        if (key==="channel_type" && value === "pump") {
            setConfig(prev => ({ ...prev, ["channel_name"]: "pump" }));
        }
    }

    const handleFormSubmit = async (e) => {
        e.preventDefault();
        try {
            onAddPwmChannel(config);
        } catch (error) {
            console.error("Update failed:", error);
    }
    }

    const isFormValid = () => {
        // Define which fields are required
        const requiredPumpFields = ["channel_type", "channel_name", "output_channel", "pulse_min", "pulse_max", "idle", "multiplier"];
        const requiredChannelConfigFields = ["channel_type", "channel_name", "output_channel", "pulse_min", "pulse_max", "direction"];

        if (config?.["channel_type"] === "pump") {
            return requiredPumpFields.every(field => config?.[field] && config?.[field] !== "" && config?.[field] !== null && config?.[field] !== undefined);
        } else if (config?.["channel_type"] === "channel_config") {
            return requiredChannelConfigFields.every(field => config?.[field] && config?.[field] !== "" && config?.[field] !== null && config?.[field] !== undefined);
        } else {
            return false
        }
    };
return (
  loading ? (<Loading />) : (
    <div className="bg-white rounded-lg shadow-md p-8 max-w-4xl mx-auto my-8">
      <h2 className="text-2xl font-bold text-gray-900 mb-6 text-center">
        Add New PWM Channel!
      </h2>
      <form className="space-y-4" onSubmit={handleFormSubmit}>
        <div className="flex flex-col">
          <label className="text-sm font-medium text-gray-700 mb-1 capitalize">
            Select Channel
          </label>
          <select
            value={config?.["channel_type"] ?? ""}
            onChange={(e) => handleInputChange(e, "channel_type")}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white cursor-pointer"
          >
            <option value="">Choose an option</option>
            <option value="pump">Pump</option>
            <option value="channel_config">Channel Config</option>
          </select>
          
          {config?.["channel_type"] && config?.["channel_type"] !== "" && (
            <>
              <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                Channel Name (*)
              </label>
              <input
                type="text"
                value={config?.["channel_type"] === "pump" ? "pump" : (config?.["channel_name"] ?? "")}
                disabled={config?.["channel_type"] === "pump"}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                onChange={(e) => handleInputChange(e, "channel_name")}
              />
              
              <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                Output Channel (*)
              </label>
              <input
                type="number"
                min="1"
                max="15"
                value={(config?.["output_channel"] ?? "")}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                onChange={(e) => handleInputChange(e, "output_channel")}
              />
              
              <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                Pulse Minimum (*)
              </label>
              <input
                type="number"
                value={(config?.["pulse_min"] ?? "")}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                onChange={(e) => handleInputChange(e, "pulse_min")}
              />
              
              <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                Pulse Maximum (*)
              </label>
              <input
                type="number"
                value={(config?.["pulse_max"] ?? "")}
                className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                onChange={(e) => handleInputChange(e, "pulse_max")}
              />
              
              {/* Show pump specific inputs and channel config inputs separately */}
              {config?.["channel_type"] === "pump" && (
                <>
                    <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Idle (*)
                    </label>
                    <input
                        type="number"
                        value={(config?.["idle"] ?? "")}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "idle")}
                    />
                    <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        multiplier (*)
                    </label>
                    <input
                        type="number"
                        value={(config?.["multiplier"] ?? "")}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "multiplier")}
                    />
                </>
              )}
              {config?.["channel_type"] === "channel_config" && (
                    <>
                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Direction (*)
                        </label>
                        <select
                        value={config?.["direction"] ?? ""}
                        onChange={(e) => handleInputChange(e, "direction")}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white cursor-pointer"
                        >
                        <option value="">Choose direction</option>
                        <option value="1">Positive (+1)</option>
                        <option value="-1">Negative (-1)</option>
                        </select>

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Center
                        </label>
                        <input
                        type="number"
                        value={config?.["center"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "center")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Deadzone
                        </label>
                        <input
                        type="number"
                        step="0.01"
                        value={config?.["deadzone"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "deadzone")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4 flex items-center">
                        <input
                            type="checkbox"
                            checked={config?.["affects_pump"] ?? false}
                            onChange={(e) => handleInputChange(e, "affects_pump")}
                            className="mr-2"
                        />
                        Affects Pump
                        </label>

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4 flex items-center">
                        <input
                            type="checkbox"
                            checked={config?.["toggleable"] ?? false}
                            onChange={(e) => handleInputChange(e, "toggleable")}
                            className="mr-2"
                        />
                        Toggleable
                        </label>

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Deadband Positive (us)
                        </label>
                        <input
                        type="number"
                        step="0.1"
                        value={config?.["deadband_us_pos"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "deadband_us_pos")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Deadband Negative (us)
                        </label>
                        <input
                        type="number"
                        step="0.1"
                        value={config?.["deadband_us_neg"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "deadband_us_neg")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4 flex items-center">
                        <input
                            type="checkbox"
                            checked={config?.["dither_enable"] ?? false}
                            onChange={(e) => handleInputChange(e, "dither_enable")}
                            className="mr-2"
                        />
                        Enable Dither
                        </label>

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Dither Amplitude (us)
                        </label>
                        <input
                        type="number"
                        step="0.1"
                        value={config?.["dither_amp_us"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "dither_amp_us")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Dither Frequency (Hz)
                        </label>
                        <input
                        type="number"
                        step="0.1"
                        value={config?.["dither_hz"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "dither_hz")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4 flex items-center">
                        <input
                            type="checkbox"
                            checked={config?.["ramp_enable"] ?? false}
                            onChange={(e) => handleInputChange(e, "ramp_enable")}
                            className="mr-2"
                        />
                        Enable Ramp
                        </label>

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Ramp Limit (us/s)
                        </label>
                        <input
                        type="number"
                        step="0.1"
                        value={config?.["ramp_limit"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "ramp_limit")}
                        />

                        <label className="text-sm font-medium text-gray-700 mb-1 capitalize mt-4">
                        Gamma
                        </label>
                        <input
                        type="number"
                        step="0.01"
                        value={config?.["gamma"] ?? ""}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        onChange={(e) => handleInputChange(e, "gamma")}
                        />
                    </>
              )}
            </>
          )}
        </div>
        
        <button 
        disabled={!isFormValid()}
        onClick={handleFormSubmit}
        className="mt-6 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition disabled:bg-gray-400 disabled:cursor-not-allowed disabled:hover:bg-gray-400"
        >
          Add PWM Channel
        </button>
        <button 
        type="button"
        onClick={() => onShowAddPwmChannelForm(false)}
        className="mt-6 mx-2 px-4 py-2 text-white rounded-lg transition bg-gray-400 hover:bg-gray-500"
        >
          Cancel
        </button>
      </form>
    </div>
  )
)
}