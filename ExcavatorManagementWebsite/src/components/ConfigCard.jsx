import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useState } from 'react';
import Loading from './Loading';
import ConfigInfo from "./ConfigInfo";

export default function ConfigCard({configs, onSetConfigs, onUpdateConfig, onDeleteChannel, loading}) {
  const [activeConfigTab, setActiveConfigTab] = useState("screen");
  return (
      loading ? (
        <Loading />
      ) : (
          <div className="bg-white rounded-lg shadow-md p-8 max-w-4xl mx-auto my-8">
            <h2 className="text-2xl font-bold text-gray-900 mb-6 text-center">
              Service Configuration Details
            </h2>

            <Tabs defaultValue={activeConfigTab} onValueChange={setActiveConfigTab}> 
              <TabsList>
                <TabsTrigger value="orientation">Orientation Tracker Configuration</TabsTrigger>
                <TabsTrigger value="pwm">PWM Configuration</TabsTrigger>
                <TabsTrigger value="screen">Screen Configuration</TabsTrigger>
                <TabsTrigger value="excavator">General Configuration</TabsTrigger>
              </TabsList>
              <TabsContent value="orientation">
                <ConfigInfo
                  configName={"orientation_tracker"}
                  configs={configs}
                  onSetConfigs={onSetConfigs}
                  onUpdateConfig={onUpdateConfig}
                 />
              </TabsContent>
              <TabsContent value="screen">
                <ConfigInfo
                  configName={"screen"}
                  configs={configs}
                  onSetConfigs={onSetConfigs}
                  onUpdateConfig={onUpdateConfig}
                 />
              </TabsContent>
              <TabsContent value="pwm">
                <ConfigInfo
                  configName={"pwm_controller"}
                  configs={configs}
                  onSetConfigs={onSetConfigs}
                  onUpdateConfig={onUpdateConfig}
                  onDeleteChannel={onDeleteChannel}
                  nestedConfigType="Channel"
                  isNestedObject={true}
                 />
              </TabsContent>
              <TabsContent value="excavator">
                <ConfigInfo
                  configName={"excavator"}
                  configs={configs}
                  onSetConfigs={onSetConfigs}
                  onUpdateConfig={onUpdateConfig}
                 />
              </TabsContent>
            </Tabs>
          </div>
      )
  );
}