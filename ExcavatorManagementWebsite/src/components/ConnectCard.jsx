import { useState } from 'react';
import Loading from './Loading';

export default function ConnectCard({ onConnectToExcavator, loading, onLoading }) {
  const [ipInput, setIpInput] = useState('');

  const handleFind = () => {
    if (!ipInput.trim()) {
      return;
    }

    onLoading(true);
    onConnectToExcavator(ipInput);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleFind();
    }
  };

    return (
      loading ? (
        <Loading />
      ) : (
        <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
          <div className="bg-white rounded-lg shadow-md p-8 w-full max-w-md">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">
              Connect to Excavator
            </h2>
            <div className="space-y-4">
              <div>
                <label htmlFor="ip-input" className="block text-sm font-medium text-gray-700 mb-2">
                  Excavator IP Address
                </label>
                <input
                  id="ip-input"
                  type="text"
                  placeholder="192.168.1.120"
                  value={ipInput}
                  onChange={(e) => setIpInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
                />
              </div>

              <button
                onClick={handleFind}
                disabled={!ipInput.trim()}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200"
              >
                Find
              </button>
            </div>
          </div>
        </div>
      )
    );
}