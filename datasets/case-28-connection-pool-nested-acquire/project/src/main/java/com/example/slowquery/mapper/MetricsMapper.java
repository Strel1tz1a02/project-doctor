package com.example.slowquery.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface MetricsMapper {

    @Select("SELECT COUNT(*) FROM telemetry_events WHERE model = #{model}")
    long countByModel(@Param("model") String model);
}
