import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Loader2, Database, ShieldAlert, Save } from 'lucide-react';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

const SettingsTab = () => {
    const [provider, setProvider] = useState('football-data');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState(null);

    useEffect(() => {
        const fetchProvider = async () => {
            try {
                const response = await api.get('/settings/provider');
                setProvider(response.data.provider);
            } catch (err) {
                console.error("Failed to fetch settings", err);
            } finally {
                setLoading(false);
            }
        };
        fetchProvider();
    }, []);

    const handleSave = async () => {
        setSaving(true);
        setMessage(null);
        try {
            await api.put('/settings/provider', { provider });
            setMessage({ type: 'success', text: 'Data Provider updated successfully!' });
        } catch (err) {
            setMessage({ type: 'error', text: 'Failed to update Data Provider.' });
            console.error(err);
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="flex justify-center items-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto space-y-6 animate-fade-in pb-12">
            <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
                <div className="flex items-center gap-3 mb-6 border-b border-gray-700 pb-4">
                    <Database className="w-6 h-6 text-teal-400" />
                    <div>
                        <h2 className="text-xl font-bold text-white">Data Provider Settings</h2>
                        <p className="text-sm text-gray-400">Manage the core API sources driving the JIT RAG Pipeline</p>
                    </div>
                </div>

                {message && (
                    <div className={`p-4 rounded-md mb-6 ${message.type === 'success' ? 'bg-green-900/30 border border-green-500/50 text-green-300' : 'bg-red-900/30 border border-red-500/50 text-red-300'}`}>
                        {message.text}
                    </div>
                )}

                <div className="space-y-6">
                    <div className="bg-gray-900/50 p-5 rounded-lg border border-gray-700">
                        <h3 className="text-lg font-semibold text-gray-200 mb-4">Primary Match Data Source</h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Option 1: Football Data */}
                            <label className={`cursor-pointer border rounded-xl p-4 transition-all ${provider === 'football-data' ? 'bg-purple-900/30 border-purple-500 shadow-[0_0_15px_rgba(168,85,247,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-4">
                                    <div className="pt-1">
                                        <input
                                            type="radio"
                                            name="provider"
                                            value="football-data"
                                            checked={provider === 'football-data'}
                                            onChange={(e) => setProvider(e.target.value)}
                                            className="w-4 h-4 text-purple-600 bg-gray-700 border-gray-600 focus:ring-purple-500 focus:ring-2"
                                        />
                                    </div>
                                    <div>
                                        <div className="font-bold text-white text-lg">football-data.org</div>
                                        <div className="text-xs text-green-400 font-medium mb-2 opacity-80 mt-1 uppercase tracking-wider">Default • Stable</div>
                                        <p className="text-sm text-gray-400 mt-1">
                                            The highly reliable, standard API used for base match statistics, fixtures, and core standings.
                                        </p>
                                    </div>
                                </div>
                            </label>

                            {/* Option 2: SofaScore / RapidAPI */}
                            <label className={`relative overflow-hidden cursor-pointer border rounded-xl p-4 transition-all ${provider === 'sofascore' ? 'bg-teal-900/30 border-teal-500 shadow-[0_0_15px_rgba(45,212,191,0.15)]' : 'bg-gray-800 border-gray-600 hover:border-gray-500'}`}>
                                <div className="flex items-start gap-4 relative z-10">
                                    <div className="pt-1">
                                        <input
                                            type="radio"
                                            name="provider"
                                            value="sofascore"
                                            checked={provider === 'sofascore'}
                                            onChange={(e) => setProvider(e.target.value)}
                                            className="w-4 h-4 text-teal-600 bg-gray-700 border-gray-600 focus:ring-teal-500 focus:ring-2"
                                        />
                                    </div>
                                    <div>
                                        <div className="font-bold text-white text-lg flex items-center gap-2">
                                            SofaScore (RapidAPI)
                                            <span className="bg-gradient-to-r from-orange-500 to-amber-500 text-white text-[10px] uppercase font-bold px-2 py-0.5 rounded-full">New</span>
                                        </div>
                                        <div className="text-xs text-orange-400/80 font-medium mb-2 mt-1 uppercase tracking-wider flex items-center gap-1">
                                            <ShieldAlert className="w-3 h-3" /> Experimental
                                        </div>
                                        <p className="text-sm text-gray-400 mt-1">
                                            Aggressive data scraping pipeline bypassing football-data logic entirely to extract deep tactical metrics and advanced team statistics.
                                        </p>
                                    </div>
                                </div>
                            </label>
                        </div>
                    </div>

                    <div className="pt-4 border-t border-gray-700 flex justify-end">
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="bg-teal-600 hover:bg-teal-500 text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 shadow-lg shadow-teal-900/40"
                        >
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            {saving ? 'Saving...' : 'Save Configuration'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SettingsTab;
