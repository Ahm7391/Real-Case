<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class MockupBookingData extends Model
{
    use HasFactory;

    /**
     * The table associated with the model.
     *
     * @var string
     */
    protected $table = 'mockup_booking_data';

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'customer_id',
        'booking_date',
        'check_in',
        'check_out',
        'net_amount_stay',
        'ota',
        'is_confirmed',
        'room_type_id'
    ];

    /**
     * Get the attributes that should be cast.
     *
     * @return array<string, string>
     */
    protected function casts(): array
    {
        return [
            'booking_date' => 'datetime',
            'check_in' => 'datetime',
            'check_out' => 'datetime',
            'customer_id' => 'integer',
            'net_amount_stay' => 'integer',
            'ota' => 'integer',
        ];
    }
}
