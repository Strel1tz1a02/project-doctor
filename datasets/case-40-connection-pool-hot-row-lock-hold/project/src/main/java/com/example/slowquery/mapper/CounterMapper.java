package com.example.slowquery.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface CounterMapper {

    @Select("SELECT value FROM counters WHERE counter_key = #{counterKey} FOR UPDATE")
    Long lockByKey(@Param("counterKey") String counterKey);

    @Insert("INSERT INTO counters(counter_key, value, updated_at_ms) VALUES (#{counterKey}, 0, #{nowMs})")
    int insertKey(@Param("counterKey") String counterKey, @Param("nowMs") long nowMs);

    @Update("UPDATE counters SET value = #{value}, updated_at_ms = #{nowMs} WHERE counter_key = #{counterKey}")
    int updateValue(@Param("counterKey") String counterKey, @Param("value") long value, @Param("nowMs") long nowMs);
}
