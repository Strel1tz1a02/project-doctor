package com.example.slowquery.mapper;

import com.example.slowquery.model.ProviderRelease;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ProviderReleaseMapper {

    @Select(
        "SELECT id, provider, release_tag, created_at " +
        "FROM provider_releases " +
        "WHERE provider = #{provider} " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<ProviderRelease> findRecentByProvider(@Param("provider") String provider,
                                               @Param("size") int size);

    @Select("SELECT * FROM provider_releases ORDER BY id")
    List<ProviderRelease> findAllReleases();
}
