<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class ScrapedCompetitorPrice extends Model
{
    use HasFactory;

    /**
     * The table associated with the model.
     *
     * @var string
     */
    protected $table = 'scraped_competitor_price';

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'competitor_id',
        'room_type_id',
        'ota_source',
        'price',
        'perks',
        'scraped_at',
        'target_date',
        'category',
    ];

    /**
     * Get the attributes that should be cast.
     *
     * @return array<string, string>
     */
    protected function casts(): array
    {
        return [
            'competitor_id' => 'string',
            'room_type_id' => 'string',
            'ota_source' => 'string',
            'price' => 'integer',
            'perks' => 'string',
            'scraped_at' => 'datetime',
            'target_date' => 'datetime',
            'category' => 'integer',
        ];
    }
}
