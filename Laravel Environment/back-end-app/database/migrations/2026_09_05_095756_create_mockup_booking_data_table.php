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
        Schema::create('mockup_booking_data', function (Blueprint $table) {
            $table->id();
            $table->integer('customer_id');
            $table->timestamp('booking_date');
            $table->timestamp('check_in');
            $table->timestamp('check_out');
            $table->integer('net_amount_stay');
            $table->integer('ota');
            $table->string('is_confirmed');
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('mockup_booking_data');
    }
};
