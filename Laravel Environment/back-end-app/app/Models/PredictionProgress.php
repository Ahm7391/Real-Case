<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class PredictionProgress extends Model
{
    use HasFactory;

    protected $table = 'prediction_progress';

    protected $fillable = [
        'job_id',
        'customer_id',
        'progress_percent',
        'stage_name',
        'message',
        'status',
    ];

    protected function casts(): array
    {
        return [
            'customer_id' => 'integer',
            'progress_percent' => 'integer',
        ];
    }
}
