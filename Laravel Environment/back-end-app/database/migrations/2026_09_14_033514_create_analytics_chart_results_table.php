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
        Schema::create('analytics_chart_results', function (Blueprint $table) {
            $table->id();                                                                                                                                                                         
            $table->string('job_id_key')->index();                                                                                                                                                
            $table->integer('customer_id')->index();                                                                                                                                              
            $table->dateTime('date_start')->nullable();                                                                                                                                           
            $table->dateTime('date_end')->nullable();                                                                                                                                             
            $table->json('result'); // Stores the "result" array directly                                                                                                                         
            $table->timestamps();
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('analytics_chart_results');
    }
};
