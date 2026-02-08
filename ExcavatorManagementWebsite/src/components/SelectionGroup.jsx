import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

export default function SelectionGroup({selectedGroup, onSelectedGroupChanged}) {
  return (
    <div className="w-full flex justify-center py-6">
      <div className="bg-white rounded-lg shadow-md p-1 border border-gray-200">
        <ToggleGroup type="single" value={selectedGroup} onValueChange={onSelectedGroupChanged} className="gap-0">
          <ToggleGroupItem value="config" className="border-r border-gray-300 hover:bg-gray-100 data-[state=on]:bg-gray-100">Config</ToggleGroupItem>
          <ToggleGroupItem value="status" className="border-r border-gray-300 hover:bg-gray-100 data-[state=on]:bg-gray-100">Status</ToggleGroupItem>
          <ToggleGroupItem value="actions" className="border-r border-gray-300 hover:bg-gray-100 data-[state=on]:bg-gray-100">Actions</ToggleGroupItem>
        </ToggleGroup>
      </div>
    </div>
  );
}