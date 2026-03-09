import React, { useState } from 'react';
import { Scale, Gavel, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';

const SupremeCourtCard = ({ supreme_court }) => {
    const [isExpanded, setIsExpanded] = useState(false);

    if (!supreme_court) return null;

    const {
        verdict_status,
        supreme_court_reasoning,
        primary_safe_pick,
        alternative_value_pick,
        variance_warning
    } = supreme_court;

    return (
        <div className="bg-gradient-to-br from-indigo-950 via-gray-900 to-slate-950 rounded-xl border-2 border-indigo-500/30 overflow-hidden shadow-2xl relative transition-all duration-500">
            {/* Background Decoration */}
            <div className="absolute top-0 right-0 p-3 opacity-10 pointer-events-none">
                <Gavel className="w-16 h-16 text-indigo-400 rotate-12" />
            </div>

            {/* Header */}
            <div className="p-3 bg-indigo-500/10 border-b border-indigo-500/20 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Scale className="w-4 h-4 text-indigo-400" />
                    <span className="text-[10px] font-black uppercase tracking-[0.2em] text-indigo-300">Supreme Court Final Ruling</span>
                </div>
                <div className={`text-[9px] font-black px-2 py-0.5 rounded border ${verdict_status === 'CONFIRMED' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                        verdict_status === 'OVERTURNED' ? 'bg-orange-500/20 text-orange-400 border-orange-500/30' :
                            'bg-gray-500/20 text-gray-400 border-gray-500/30'
                    }`}>
                    {verdict_status}
                </div>
            </div>

            <div className="p-4 space-y-4">
                {/* Reasoning with Expand/Collapse */}
                <div className="relative">
                    <p className={`text-base text-indigo-50 leading-relaxed font-medium italic transition-all duration-300 ${isExpanded ? '' : 'line-clamp-3'}`}>
                        "{supreme_court_reasoning}"
                    </p>
                    {supreme_court_reasoning && supreme_court_reasoning.length > 150 && (
                        <button
                            onClick={() => setIsExpanded(!isExpanded)}
                            className="mt-2 text-[10px] font-bold text-indigo-400 hover:text-indigo-300 uppercase tracking-widest flex items-center gap-1 transition-colors"
                        >
                            {isExpanded ? (
                                <><ChevronUp className="w-3 h-3" /> Show Less</>
                            ) : (
                                <><ChevronDown className="w-3 h-3" /> Show Full Judicial Opinion</>
                            )}
                        </button>
                    )}
                </div>

                {/* Picks Grid - Larger Text */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="bg-black/40 rounded-lg p-3 border border-indigo-500/15 group hover:border-indigo-500/30 transition-colors">
                        <div className="text-[9px] text-indigo-400 font-bold uppercase mb-1 tracking-wider">Arbiter's Safe Pick</div>
                        <div className="text-base md:text-lg font-black text-white leading-tight">{primary_safe_pick?.tip || 'N/A'}</div>
                        <div className="text-[10px] text-gray-500 uppercase tracking-tighter mt-0.5">{primary_safe_pick?.market}</div>
                    </div>
                    <div className="bg-black/40 rounded-lg p-3 border border-purple-500/15 group hover:border-purple-500/30 transition-colors">
                        <div className="text-[9px] text-purple-400 font-bold uppercase mb-1 tracking-wider">Expected Value (EV) Pick</div>
                        <div className="text-base md:text-lg font-black text-white leading-tight">{alternative_value_pick?.tip || 'N/A'}</div>
                        <div className="text-[10px] text-gray-500 uppercase tracking-tighter mt-0.5">{alternative_value_pick?.market}</div>
                    </div>
                </div>

                {/* Variance Warning - Larger Text */}
                {variance_warning && (
                    <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3 flex gap-3 items-start">
                        <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                        <div className="text-sm text-red-200/90 italic">
                            <span className="font-black uppercase text-[10px] block mb-1 text-red-400 tracking-[0.1em]">Variance Warning:</span>
                            {variance_warning}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default SupremeCourtCard;
