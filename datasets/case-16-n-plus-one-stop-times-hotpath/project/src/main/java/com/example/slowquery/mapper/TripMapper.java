package com.example.slowquery.mapper;

import com.example.slowquery.model.StopTime;
import com.example.slowquery.model.Trip;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface TripMapper {

    @Select(
        "SELECT trip_id, block_id, route_id, service_id, trip_headsign, created_at FROM trips " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<Trip> findRecentTrips(@Param("size") int size);

    @Select(
        "SELECT trip_id, stop_sequence, stop_id, arrival_time, departure_time FROM stop_times " +
        "WHERE trip_id = #{tripId} " +
        "ORDER BY stop_sequence"
    )
    List<StopTime> findStopTimesByTripId(@Param("tripId") String tripId);
}
