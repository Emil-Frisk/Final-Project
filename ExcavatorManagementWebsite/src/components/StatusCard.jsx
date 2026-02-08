import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import StatusInfo from "./StatusInfo"
import Loading from "./Loading"

export default function StatusCard({loading,activeStatusTab, onActiveStatusTabChanged, statuses}) {
  return (
    loading ? (<Loading/>) : (
        <div className="bg-white rounded-lg shadow-md p-8 max-w-4xl mx-auto my-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-6 text-center">
            Status Details
          </h2>

          <Tabs defaultValue={activeStatusTab} onValueChange={onActiveStatusTabChanged}> 
            <TabsList>
              <TabsTrigger value="excavator">Excavator</TabsTrigger>
              <TabsTrigger value="udp">UDPSocket</TabsTrigger>
              <TabsTrigger value="orientation">Orientation Tracker</TabsTrigger>
            </TabsList>
            <TabsContent value="orientation">
              <StatusInfo status={statuses?.["orientation"] ?? null}/>
            </TabsContent>
            <TabsContent value="udp">
              <StatusInfo status={statuses?.["udp"] ?? null}/>
            </TabsContent>
            <TabsContent value="excavator">
              <StatusInfo status={statuses?.["excavator"] ?? null}/>
            </TabsContent>
          </Tabs>
        </div>
      )
  )
}
