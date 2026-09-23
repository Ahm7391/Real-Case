<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('forecast_result', function (Blueprint $table) {
            $table->id();
            $table->integer('customer_id');
            $table->integer('room_type_id');
            $table->dateTime('forecast_date')->index();
            $table->decimal('forecasted_price', 15, 2)->default(0);
            $table->decimal('corrected_price', 15, 2)->default(0);
            $table->string('status', 50)->default('processed');
            $table->timestamps();

            $table->unique(
                ['customer_id', 'room_type_id', 'forecast_date'],
                'uq_forecast_customer_room_date'
            );
            $table->index(['customer_id', 'forecast_date'], 'idx_forecast_customer_date');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('forecast_result');
    }
};
