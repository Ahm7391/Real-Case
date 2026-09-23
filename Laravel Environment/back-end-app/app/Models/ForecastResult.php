<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class ForecastResult extends Model
{
    use HasFactory;

    /**
     * The table associated with the model.
     *
     * @var string
     */
    protected $table = 'forecast_result';

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'customer_id',
        'room_type_id',
        'forecast_date',
        'forecasted_price',
        'corrected_price',
        'status',
    ];

    /**
     * Get the attributes that should be cast.
     *
     * @return array<string, string>
     */
    protected function casts(): array
    {
        return [
            'customer_id' => 'integer',
            'room_type_id' => 'integer',
            'forecast_date' => 'datetime',
            'forecasted_price' => 'decimal:2',
            'corrected_price' => 'decimal:2',
            'status' => 'string',
        ];
    }
}
