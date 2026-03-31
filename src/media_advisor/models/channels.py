"""Channel config models — mirrors channels/channels.json shape."""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class FetchRuleRss(BaseModel):
    type: Literal["rss"]
    channel_id: str | None = None
    channel_url: str | None = None
    last_n: int | None = None
    exclude_title_contains: str | None = None
    exclude_live: bool = False


class FetchRulePlaylist(BaseModel):
    type: Literal["playlist"]
    playlist_id: str
    last_n: int | None = None
    exclude_title_contains: str | None = None
    exclude_live: bool = False


class FetchRuleTranscriptApi(BaseModel):
    type: Literal["transcript_api"]
    channel_url: str | None = None
    channel_id: str | None = None
    last_n: int | None = None
    title_contains: str | None = None
    exclude_title_contains: str | None = None
    exclude_live: bool = False


class FetchRuleManual(BaseModel):
    type: Literal["manual"]


FetchRule = Annotated[
    Union[FetchRuleRss, FetchRulePlaylist, FetchRuleTranscriptApi, FetchRuleManual],
    Field(discriminator="type"),
]


class ChannelConfig(BaseModel):
    id: str
    name: str
    order: int = 999
    video_list: str
    fetch_rule: FetchRule | None = None


class ChannelsConfig(BaseModel):
    channels: list[ChannelConfig]
