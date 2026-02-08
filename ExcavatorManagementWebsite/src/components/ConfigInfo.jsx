import DeleteButton from "./DeleteButton";
import FormLblInGroup from "./FormLblInGroup";
import PrimaryButton from "./PrimaryButton";

export default function ConfigInfo({configName, configs, onSetConfigs, onUpdateConfig, onDeleteChannel, isNestedObject=false, nestedConfigType="Channel"}) {
  const handleInputChange = (e, key, parentKey = null) => {
    const { value } = e.target;
    console.log(`Config Name: ${configName} - Key: ${key} - parentKey: ${parentKey}`)
    if (parentKey!=null) { // Nested config
      onSetConfigs(prev => ({
        ...prev, // Keep other configs the same
        [configName]: {
        ...prev[configName], // Keep other parentKeys the same
          [parentKey]: {
              ...prev[configName][parentKey],
              [key]: value
          }
        }
      }));
    } else {
        onSetConfigs(prev => ({
        ...prev,
        [configName]: {
            ...prev[configName],
            [key]: value
        }
        }));
    }
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    try {
      onUpdateConfig(configName);
    } catch (error) {
      console.error("Update failed:", error);
    }
  };

return (
    configs==null ? <p>Loading configs...</p> : (
    <form className="space-y-4" onSubmit={handleFormSubmit}>
        {isNestedObject ? (
            <>
            {Object.entries(configs[configName]).map(([parentKey, nestedCfg]) => (
                <div key={parentKey} className="border border-gray-200 rounded-lg p-6 mb-6">
                    <h2 className="text-2xl font-bold text-gray-900 mb-6">
                        {parentKey}
                    </h2>
                    {Object.entries(nestedCfg).map(([key, value]) => (
                        <FormLblInGroup 
                            key={key}
                            inputType={"text"}
                            labelText={key.replace(/_/g, ' ')}
                            inputValue={configs[configName][parentKey][key]}
                            onInputChanged={(e) => handleInputChange(e, key, parentKey)}
                        />
                    ))}
                    <DeleteButton text={`Delete ${nestedConfigType}`} onClick={(e) => onDeleteChannel(channel_name)} />
                </div>
            ))}
            </>
        ) : (
            <div>
                {Object.entries(configs[configName]).map(([key, value]) => (
                    <FormLblInGroup 
                        inputType={"text"}
                        labelText={key.replace(/_/g, ' ')}
                        inputValue={configs[configName][key]}
                        onInputChanged={(e) => handleInputChange(e, key, null)}
                        key={key}
                    />
                ))}
            </div>
        )}
        <PrimaryButton text={`Update ${configName}`.replace(/_/g, " ")}/>
    </form>
    )
);
}