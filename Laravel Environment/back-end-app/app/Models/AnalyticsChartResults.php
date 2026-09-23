<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class AnalyticsChartResults extends Model
{
    use HasFactory;

    protected $table = 'analytics_chart_results';
    protected $fillable = [                                                                                                                                                               
        'job_id_key',                                                                                                                                                                     
        'customer_id',                                                                                                                                                                    
        'date_start',                                                                                                                                                                     
        'date_end',                                                                                                                                                                       
        'result',                                                                                                                                                                       
    ];                                                                                                                                                                                    
                                                                                                                                                                                            
    protected function casts(): array                                                                                                                                                     
    {                                                                                                                                                                                     
        return [                                                                                                                                                                          
            'date_start' => 'datetime',                                                                                                                                                   
            'date_end' => 'datetime',                                                                                                                                                     
            'result' => 'array', // Automatically decodes JSON into PHP array                                                                                                             
        ];                                                                                                                                                                                
    }
}
