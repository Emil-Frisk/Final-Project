import { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import ConnectCard from './components/ConnectCard';
import ConfigCard from './components/ConfigCard';
import SelectionGroup from './components/SelectionGroup'
import StatusCard from './components/StatusCard'
import ActionsCard from './components/ActionsCard';
import { Toaster, toast } from 'sonner'

export default function App() {
  const wsRef = useRef(null);
  const statusCoroutines = useRef([]);
  
  // States
  const [excavatorFound, setExcavatorFound]= useState(false);
  const [configs, setConfigs] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const [activeStatusTab, setActiveStatusTab] = useState("excavator");
  const [selectedGroup, setSelectedGroup] = useState("config");
  const [statuses, setStatuses] = useState(null)
  const [showAddPwmChannelForm, setShowAddPwmChannelForm] = useState(false);

  // cleanup
  useEffect(() => {
    return () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      socket.close();
      console.log("Socket closed");
    } else {
      console.log("Socket not open, skipping close");
    }
    stopStatusCoroutines()
  };
  }, []);

  // Error toast handler - runs whenever error changes
  useEffect(() => {
    if (error) {
      toast.error(error, {
        duration: 5000,
        style: {
          background: 'crimson',
          color: 'white'
        },
      });
      setError(null);
    } else if(info) {
      toast.info(info)
      setInfo(null);
    }
  }, [error,info, toast]);

  const connectToExcavator = (ip) => {
    const socket = new WebSocket(`ws://${ip}:5432`);

    socket.onopen = () => {
      toast.info("Found the excavator!")
      setExcavatorFound(true);
      setLoading(false)
      sendMessage({action: 'get_screen_config'})
      sendMessage({action: 'get_excavator_config'})
      sendMessage({action: 'get_pwm_config'})
      sendMessage({action: 'get_orientation_tracker_config'})
    };

    socket.onmessage = (event) => {
      handleMessage(event.data);
    };

    socket.onerror = (error) => {
      console.error('WebSocket error:', error);
      if (!excavatorFound) {
        setError('Connection to excavator did not succeed - Make sure you are in the same network and excavator is up and running.');
      } else {
        setError('Connection to the excavator has been unexpectedly lost.');
      }
      stopStatusCoroutines()
      setLoading(false)
      setExcavatorFound(false)
    };

    socket.onclose = () => {
      console.log('ExcavatorAPI has closed the connection');
      setExcavatorFound(false);
    };

    wsRef.current=socket
  }

  const removeObjEntry = (keyToRemove, obj) => {
    return Object.keys(obj)
    .filter(key => key !== keyToRemove)
    .reduce((acc, key) => ({...acc, [key]: obj[key] }), {})
  }

  const addPwmChannel = (config) => {
    var channelType=config["channel_type"]
    var channelName = config["channel_name"]
    delete config["channel_type"]
    delete config["channel_name"]
    var test={
      action: "add_pwm_channel",
      channel_name: channelName,
      channel_type: channelType,
      config: config,
    }
    sendMessage(test)
  }

  // Handle incoming WebSocket messages
  const handleMessage = (data) => {
    try {
      const message = JSON.parse(data);

      if (message.event === 'error') {
        var error=message.error
        var context=error?.["context"]
        if (context && context==="status_orientation_tracker") {
          cancelCouritine("orientation")
          setStatuses((prev) => removeObjEntry("orientation", prev))
        } else if (context && context==="status_excavator") {
          cancelCouritine("excavator")
          setStatuses((prev) => removeObjEntry("excavator", prev))
        } else if (context && context==="status_udp") {
          cancelCouritine("udp")
          setStatuses((prev) => removeObjEntry("udp", prev))
        } 
        setError(error.message || 'An error occurred');
        setLoading(false);
      } else if (message.event === 'configuration') {
          // Cache the config based on type
          let ctx=message.context
          let cfg=JSON.parse(message.config)
          var target=message?.target

          if (ctx.includes("configure_")) {
            toast.info(`Configuration for ${message.target} was successful!`)
            setLoading(false)
          } else if(ctx==="remove_pwm_channel") {
            var channel_name = message.channel_name
            toast.info(`Successfully removed ${channel_name}s pwm channel configuration`)
            setLoading(false)
          } else if (ctx==="add_pwm_channel") {
            var channel_name = message.channel_name
            toast.info(`Successfully added ${channel_name} PWM channel!`)
            setShowAddPwmChannelForm(false)
            setLoading(false)
          } 

          if (target === 'pwm_controller') {
            setConfigs((prev) => ({...prev, [message.target]: cfg["CHANNEL_CONFIGS"] }))
          } else {
            setConfigs((prev) => ({...prev, [message.target]: cfg }))
          }

      } else if (message.event==="status") {
        var target=message.target
        setStatuses((prev) => ({...prev, [target]: message.status }))
        setLoading(false)
      } else if (message.event==="started_screen") {
        toast.info("Successfully started the screen")
      } else if (message.event==="stopped_screen") {
        toast.info("Successfully stopped the screen")
      }
    } catch (err) {
      console.error('Failed to parse message:', err);
    }
  };

  const cancelCouritine = (name) => {
    for (let i=0;i<statusCoroutines.current.length;i++) {
      if (statusCoroutines.current[i]["name"]===name) {
        clearInterval(statusCoroutines.current[i]["id"])
        statusCoroutines.current=statusCoroutines.current.filter((_,ind) => ind !== i)
        console.log(`Stopped ${name}s status coroutine!`)
        return true
      }
    }
    console.error(`Failed to cancel couritine ${name} - Could not find it`)
    return false
  }

  const getExcavatorStatus = () => {
    sendMessage({action: "status_excavator"})
  }

  const getOrientationTrackerStatus = () => {
      sendMessage({action: "status_orientation_tracker"})
  }

  const getUdpStatus = () => {
    sendMessage({action: "status_udp"})
  }

  const stopStatusCoroutines = () => {
    for (let i=0;i<statusCoroutines.current.length;i++) {
      clearInterval(statusCoroutines.current[i]["id"])
      console.log(`Stopped ${statusCoroutines.current[i]["name"]}s status coroutine!`)
    }
    statusCoroutines.current=[]
  }

  const handleSelectedGroupChanged = (value) => {
    if (value === "status") {
      setLoading(true)
      const id = setInterval(getExcavatorStatus, 1000)
      statusCoroutines.current.push({id: id, name: "excavator"})
    } else {
      stopStatusCoroutines()
      setStatuses(null)
    }
    setSelectedGroup(value)
  }

  const checkCoroutineExistance = (name) => {
    for (let i=0;i<statusCoroutines.current.length;i++) {
      if (statusCoroutines.current[i]["name"]===name) {
        return true
      }
    }
    return false
  }

  const handleActiveStatusTabChanged = (value) => {
    if (value==="udp") {
      var r=checkCoroutineExistance("udp")
      if (!r) {
        const id = setInterval(getUdpStatus, 1000)
        statusCoroutines.current.push({id: id, name: "udp" })
      }
    } else if (value==="orientation") {
      var r=checkCoroutineExistance("orientation")
      if(!r){
        const id = setInterval(getOrientationTrackerStatus, 1000)
        statusCoroutines.current.push({id: id, name: "orientation" })
      }
    } 
    setActiveStatusTab(value)
  }

  const updateConfig = (cfg_name) => { 
    setLoading(true)
    var cfg=configs[cfg_name]
    if (cfg_name === "screen") {
      sendMessage({
        action: "configure_screen",
        render_time: cfg["render_time"],
        font_size_header: cfg["font_size_header"],
        font_size_body: cfg["font_size_body"]
      })
     } else if (cfg_name === "pwm_controller") {
        sendMessage({
          action: "configure_pwm_controller",
          channel_configs: cfg
        })
      } else if (cfg_name==="orientation_tracker"){ 
        sendMessage({
          action: "configure_orientation_tracker",
          ...cfg
        })
      } else if (cfg_name==="excavator"){ 
        sendMessage({
          action: "configure_excavator",
          ...cfg
        })
      } else {
        console.error(`Unknown config name: ${cfg_name}`)
      }
  }

  const startScreen = () => {
    sendMessage({action: "start_screen"})
  }

  const stopScreen = () => {
    sendMessage({action: "stop_screen"})
  }

  const deletePwmChannel = (channel_name) => {
    sendMessage({action: "remove_pwm_channel", channel_name: channel_name })
  }

  const sendMessage = (action) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(action));
    } else {
      setError('WebSocket not connected');
    }
};

    return (
      <div className="tihi w-full min-h-screen bg-gray-50">
        <Toaster />
        <Header />
        
        <main className="w-full px-4">

           {!excavatorFound ? (
            <ConnectCard 
              onConnectToExcavator={connectToExcavator}
              loading={loading}
              onLoading={setLoading}
            />
          ) : (
            <>
              <SelectionGroup
                selectedGroup={selectedGroup}
                onSelectedGroupChanged={handleSelectedGroupChanged}
               />
               { selectedGroup === "config" ? (
                <ConfigCard
                configs={configs}
                onSetConfigs={setConfigs}
                onUpdateConfig={updateConfig}
                onDeleteChannel={deletePwmChannel}
                loading={loading}
              />
               ) : selectedGroup === "status" ? 
               (
                <StatusCard
                  loading={loading}
                  activeStatusTab={activeStatusTab}
                  onActiveStatusTabChanged={handleActiveStatusTabChanged}
                  statuses={statuses}
                 />
               ) : ( 
                <ActionsCard 
                loading={loading}
                onStartScreen={startScreen}
                onStopScreen={stopScreen}
                showAddPwmChannelForm={showAddPwmChannelForm}
                onShowAddPwmChannelForm={setShowAddPwmChannelForm}
                onAddPwmChannel={addPwmChannel}
                />
               )}
          </>
          )}
        </main>
      </div>
    );
}