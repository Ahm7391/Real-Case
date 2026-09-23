<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class AnalyticsResult extends Model
{
    use HasFactory;

    /**
     * The table associated with the model.
     *
     * @var string
     */
    protected $table = 'analytics_result';

    /**
     * Status code constants.
     */
    public const STATUS_IN_PROGRESS = 1;
    public const STATUS_SUCCESS = 2;
    public const STATUS_FAULT = 3;

    /**
     * The attributes that are mass assignable.
     *
     * @var list<string>
     */
    protected $fillable = [
        'job_id_key',
        'customer_id',
        'status',
        'message',
        'date_request',
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
            'status' => 'integer',
            'date_request' => 'datetime',
        ];
    }

    /**
     * Get human-readable status badge label.
     */
    public function getStatusLabelAttribute(): string
    {
        return match ($this->status) {
            self::STATUS_IN_PROGRESS => '1 [IN PROGRESS]',
            self::STATUS_SUCCESS => '2 [SUCCESS]',
            self::STATUS_FAULT => '3 [FAULT]',
            default => (string) $this->status,
        };
    }

    /**
     * Get status badge style class.
     */
    public function getStatusBadgeClassAttribute(): string
    {
        return match ($this->status) {
            self::STATUS_IN_PROGRESS => 'badge-light-warning text-warning border border-warning',
            self::STATUS_SUCCESS => 'badge-light-success text-success border border-success',
            self::STATUS_FAULT => 'badge-light-danger text-danger border border-danger',
            default => 'badge-light-secondary text-secondary border border-secondary',
        };
    }
}
